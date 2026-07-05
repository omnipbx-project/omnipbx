from __future__ import annotations

import csv
import io
import json
import re
import threading
import time
import zipfile
from dataclasses import dataclass
from datetime import datetime
from urllib import parse, request
from xml.etree import ElementTree

import psycopg
from psycopg.rows import dict_row

from app.core.settings import get_settings
from app.features.status.service import collect_status_snapshot
from app.services.ami import ami_originate_extension
from app.services.setup import get_system_settings


CAMPAIGN_STATUSES = {"draft", "running", "paused", "finished"}
DIALING_MODES = {"preview", "auto"}
_AUTODIALER_THREAD: threading.Thread | None = None
_AUTODIALER_STOP = threading.Event()
_AUTODIALER_LOCK = threading.Lock()


@dataclass
class LeadImportResult:
    imported: int = 0
    duplicates: int = 0
    invalid: int = 0
    failed_rows: list[dict[str, str]] | None = None

    @property
    def message(self) -> str:
        return (
            f"{self.imported} leads imported. "
            f"{self.duplicates} already existed. "
            f"{self.invalid} need fixing."
        )


def list_campaigns(connection: psycopg.Connection) -> list[dict]:
    with connection.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT
                campaign.*,
                COUNT(lead.id) AS lead_count,
                COUNT(lead.id) FILTER (WHERE lead.status = 'ready') AS ready_count,
                COUNT(lead.id) FILTER (WHERE lead.status = 'invalid') AS invalid_count,
                COUNT(lead.id) FILTER (
                    WHERE lead.status IN ('called', 'done', 'completed', 'success')
                       OR lower(COALESCE(lead.last_result, '')) IN ('answered', 'success', 'completed', 'called')
                ) AS successful_count,
                COUNT(lead.id) FILTER (
                    WHERE lead.status IN ('failed', 'busy', 'no_answer')
                       OR lower(COALESCE(lead.last_result, '')) IN ('failed', 'busy', 'noanswer', 'no_answer', 'no answer', 'cancel', 'congestion')
                ) AS failed_count
            FROM autodialer_campaigns campaign
            LEFT JOIN autodialer_leads lead ON lead.campaign_id = campaign.id
            GROUP BY campaign.id
            ORDER BY campaign.created_at DESC
            """
        )
        return [_normalize_campaign(row) for row in cursor.fetchall()]


def start_auto_dialer_worker() -> None:
    global _AUTODIALER_THREAD
    with _AUTODIALER_LOCK:
        if _AUTODIALER_THREAD and _AUTODIALER_THREAD.is_alive():
            return
        _AUTODIALER_STOP.clear()
        _AUTODIALER_THREAD = threading.Thread(target=_auto_dialer_loop, name="omnipbx-auto-dialer", daemon=True)
        _AUTODIALER_THREAD.start()


def stop_auto_dialer_worker() -> None:
    _AUTODIALER_STOP.set()


def get_campaign(connection: psycopg.Connection, campaign_id: int) -> dict | None:
    with connection.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT
                campaign.*,
                COUNT(lead.id) AS lead_count,
                COUNT(lead.id) FILTER (WHERE lead.status = 'ready') AS ready_count,
                COUNT(lead.id) FILTER (WHERE lead.status = 'invalid') AS invalid_count,
                COUNT(lead.id) FILTER (
                    WHERE lead.status IN ('called', 'done', 'completed', 'success')
                       OR lower(COALESCE(lead.last_result, '')) IN ('answered', 'success', 'completed', 'called')
                ) AS successful_count,
                COUNT(lead.id) FILTER (
                    WHERE lead.status IN ('failed', 'busy', 'no_answer')
                       OR lower(COALESCE(lead.last_result, '')) IN ('failed', 'busy', 'noanswer', 'no_answer', 'no answer', 'cancel', 'congestion')
                ) AS failed_count
            FROM autodialer_campaigns campaign
            LEFT JOIN autodialer_leads lead ON lead.campaign_id = campaign.id
            WHERE campaign.id = %(campaign_id)s
            GROUP BY campaign.id
            """,
            {"campaign_id": campaign_id},
        )
        row = cursor.fetchone()
        return _normalize_campaign(row) if row else None


def save_campaign(
    connection: psycopg.Connection,
    *,
    name: str,
    trunk_name: str,
    dialing_mode: str,
    next_call_wait_seconds: int,
    assigned_users: list[str],
    assigned_groups: list[str],
    campaign_id: int | None = None,
) -> dict:
    cleaned_name = _clean_name(name)
    cleaned_trunk = trunk_name.strip()
    cleaned_mode = dialing_mode if dialing_mode in DIALING_MODES else "preview"
    wait_seconds = max(1, min(int(next_call_wait_seconds or 5), 600))
    users = sorted({item.strip() for item in assigned_users if item.strip()})
    groups = sorted({item.strip() for item in assigned_groups if item.strip()})
    if not cleaned_name:
        raise ValueError("Campaign name is required.")
    if not cleaned_trunk:
        raise ValueError("Choose the calling line.")
    if not users and not groups:
        raise ValueError("Choose at least one caller or group.")

    values = {
        "campaign_id": campaign_id,
        "name": cleaned_name,
        "trunk_name": cleaned_trunk,
        "dialing_mode": cleaned_mode,
        "next_call_wait_seconds": wait_seconds,
        "assigned_users": json.dumps(users),
        "assigned_groups": json.dumps(groups),
    }
    with connection.cursor(row_factory=dict_row) as cursor:
        if campaign_id:
            cursor.execute(
                """
                UPDATE autodialer_campaigns
                SET name = %(name)s,
                    trunk_name = %(trunk_name)s,
                    dialing_mode = %(dialing_mode)s,
                    next_call_wait_seconds = %(next_call_wait_seconds)s,
                    assigned_users = %(assigned_users)s::jsonb,
                    assigned_groups = %(assigned_groups)s::jsonb,
                    updated_at = NOW()
                WHERE id = %(campaign_id)s
                RETURNING *
                """,
                values,
            )
        else:
            cursor.execute(
                """
                INSERT INTO autodialer_campaigns (
                    name, trunk_name, dialing_mode, next_call_wait_seconds, assigned_users, assigned_groups
                )
                VALUES (
                    %(name)s, %(trunk_name)s, %(dialing_mode)s, %(next_call_wait_seconds)s,
                    %(assigned_users)s::jsonb, %(assigned_groups)s::jsonb
                )
                RETURNING *
                """,
                values,
            )
        row = cursor.fetchone()
        if not row:
            raise ValueError("Campaign was not found.")
        return _normalize_campaign(row)


def delete_campaign(connection: psycopg.Connection, campaign_id: int) -> bool:
    with connection.cursor(row_factory=dict_row) as cursor:
        cursor.execute("DELETE FROM autodialer_campaigns WHERE id = %(campaign_id)s RETURNING id", {"campaign_id": campaign_id})
        return bool(cursor.fetchone())


def delete_lead(connection: psycopg.Connection, campaign_id: int, lead_id: int) -> bool:
    with connection.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            DELETE FROM autodialer_leads
            WHERE id = %(lead_id)s AND campaign_id = %(campaign_id)s
            RETURNING id
            """,
            {"campaign_id": campaign_id, "lead_id": lead_id},
        )
        return bool(cursor.fetchone())


def set_campaign_status(connection: psycopg.Connection, campaign_id: int, status: str) -> bool:
    cleaned = status if status in CAMPAIGN_STATUSES else "draft"
    with connection.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            UPDATE autodialer_campaigns
            SET status = %(status)s, updated_at = NOW()
            WHERE id = %(campaign_id)s
            RETURNING id
            """,
            {"campaign_id": campaign_id, "status": cleaned},
        )
        return bool(cursor.fetchone())


def list_leads(connection: psycopg.Connection, campaign_id: int) -> list[dict]:
    with connection.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT id, lead_name, phone_number, dial_number, company, email, note, status,
                   TO_CHAR(created_at, 'YYYY-MM-DD HH24:MI') AS added_at
            FROM autodialer_leads
            WHERE campaign_id = %(campaign_id)s
            ORDER BY created_at DESC, id DESC
            LIMIT 500
            """,
            {"campaign_id": campaign_id},
        )
        return list(cursor.fetchall())


def list_all_leads(connection: psycopg.Connection, campaign_id: int | None = None) -> list[dict]:
    filters = []
    params: dict[str, int] = {}
    if campaign_id:
        filters.append("lead.campaign_id = %(campaign_id)s")
        params["campaign_id"] = campaign_id
    where_clause = f"WHERE {' AND '.join(filters)}" if filters else ""
    with connection.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            f"""
            SELECT
                lead.id,
                lead.campaign_id,
                lead.lead_name,
                lead.phone_number,
                lead.dial_number,
                lead.company,
                lead.email,
                lead.note,
                lead.status,
                TO_CHAR(lead.created_at, 'YYYY-MM-DD HH24:MI') AS added_at,
                campaign.name AS campaign_name,
                campaign.status AS campaign_status,
                campaign.dialing_mode
            FROM autodialer_leads lead
            JOIN autodialer_campaigns campaign ON campaign.id = lead.campaign_id
            {where_clause}
            ORDER BY lead.created_at DESC, lead.id DESC
            LIMIT 1000
            """,
            params,
        )
        return list(cursor.fetchall())


def list_campaign_callers(connection: psycopg.Connection, campaign: dict) -> list[str]:
    assigned_users = _json_list(campaign.get("assigned_users"))
    assigned_groups = _json_list(campaign.get("assigned_groups"))
    callers: list[str] = []
    for extension in assigned_users:
        if extension not in callers:
            callers.append(extension)
    if assigned_groups:
        with connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT profile.extension
                FROM user_profiles profile
                JOIN user_groups group_row ON group_row.id = profile.group_id
                JOIN extensions extension ON extension.extension = profile.extension
                WHERE group_row.name = ANY(%(groups)s)
                  AND extension.enabled = TRUE
                ORDER BY profile.extension
                """,
                {"groups": assigned_groups},
            )
            for row in cursor.fetchall():
                extension = str(row["extension"])
                if extension not in callers:
                    callers.append(extension)
    return callers


def list_ready_campaign_callers(connection: psycopg.Connection, campaign: dict) -> list[str]:
    assigned_callers = list_campaign_callers(connection, campaign)
    if not assigned_callers:
        return []
    online_extensions = _online_extensions(connection)
    busy_extensions = _busy_extensions()
    return [
        extension
        for extension in assigned_callers
        if extension in online_extensions and extension not in busy_extensions
    ]


def start_lead_call(connection: psycopg.Connection, campaign_id: int, lead_id: int, caller_extension: str = "") -> str:
    campaign = get_campaign(connection, campaign_id)
    if not campaign:
        raise ValueError("Campaign was not found.")
    assigned_callers = list_campaign_callers(connection, campaign)
    ready_callers = list_ready_campaign_callers(connection, campaign)
    caller = caller_extension.strip() or (ready_callers[0] if ready_callers else "")
    if not caller or caller not in assigned_callers:
        raise ValueError("Choose an assigned caller before starting the call.")
    if caller not in ready_callers:
        raise ValueError(f"Extension {caller} is not ready. The agent must be online and not already on a call.")
    with connection.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT id, phone_number, dial_number, status
            FROM autodialer_leads
            WHERE id = %(lead_id)s AND campaign_id = %(campaign_id)s
            """,
            {"campaign_id": campaign_id, "lead_id": lead_id},
        )
        lead = cursor.fetchone()
        if not lead:
            raise ValueError("Lead was not found.")
        if lead["status"] != "ready":
            raise ValueError("Only ready leads can be called.")
        dial_number = re.sub(r"[^0-9+*#]", "", str(lead.get("dial_number") or lead.get("phone_number") or ""))
        if not dial_number:
            raise ValueError("Lead has no dialable number.")
        ami_originate_extension(
            f"PJSIP/{caller}",
            get_settings().internal_context,
            dial_number,
            caller_id=caller,
        )
        cursor.execute(
            """
            UPDATE autodialer_leads
            SET status = 'called',
                attempts = attempts + 1,
                last_call_at = NOW(),
                last_result = 'started',
                updated_at = NOW()
            WHERE id = %(lead_id)s AND campaign_id = %(campaign_id)s
            """,
            {"campaign_id": campaign_id, "lead_id": lead_id},
        )
    return f"Calling {lead['phone_number']} from {caller}. Answer extension {caller} to connect the lead."


def run_auto_dialer_tick(connection: psycopg.Connection) -> int:
    started = 0
    _finish_completed_auto_campaigns(connection)
    campaigns = _running_auto_campaigns(connection)
    for campaign in campaigns:
        ready_callers = list_ready_campaign_callers(connection, campaign)
        if not ready_callers:
            continue
        caller = ready_callers[0]
        lead = _claim_next_ready_lead(connection, int(campaign["id"]))
        if not lead:
            _finish_campaign_if_empty(connection, int(campaign["id"]))
            continue
        try:
            dial_number = re.sub(r"[^0-9+*#]", "", str(lead.get("dial_number") or lead.get("phone_number") or ""))
            if not dial_number:
                _mark_lead_invalid(connection, int(campaign["id"]), int(lead["id"]), "missing_number")
                continue
            ami_originate_extension(
                f"PJSIP/{caller}",
                get_settings().internal_context,
                dial_number,
                caller_id=caller,
            )
            _mark_lead_called(connection, int(campaign["id"]), int(lead["id"]), "auto_started")
            started += 1
        except Exception as exc:
            _release_claimed_lead(connection, int(campaign["id"]), int(lead["id"]), str(exc))
    return started


def import_leads(
    connection: psycopg.Connection,
    *,
    campaign_id: int,
    rows: list[dict[str, str]],
    phone_column: str,
    name_column: str = "",
    company_column: str = "",
    email_column: str = "",
    note_column: str = "",
) -> LeadImportResult:
    result = LeadImportResult(failed_rows=[])
    dialing_region = str(get_system_settings(connection).get("dialing_region") or "+880")
    with connection.cursor(row_factory=dict_row) as cursor:
        for index, row in enumerate(rows, start=1):
            source_phone = _field(row, phone_column) if phone_column else ""
            if not source_phone or not _normalize_phone(source_phone):
                source_phone = _find_phone_value(row)
            phone, dial_number = _normalize_phone_pair(source_phone, dialing_region)
            lead_name = _field(row, name_column) if name_column else ""
            company = _field(row, company_column) if company_column else ""
            email = _field(row, email_column) if email_column else ""
            note = _field(row, note_column) if note_column else ""
            if not phone:
                result.invalid += 1
                result.failed_rows.append({"row": str(index), "reason": "Missing or invalid phone number"})
                continue
            lead_name = _unique_lead_name(cursor, campaign_id, lead_name or phone, phone)
            try:
                cursor.execute(
                    """
                    INSERT INTO autodialer_leads (
                        campaign_id, lead_name, phone_number, dial_number, company, email, note, status
                    )
                    VALUES (
                        %(campaign_id)s, %(lead_name)s, %(phone_number)s, %(dial_number)s,
                        %(company)s, %(email)s, %(note)s, 'ready'
                    )
                    ON CONFLICT (campaign_id, phone_number) DO NOTHING
                    RETURNING id
                    """,
                    {
                        "campaign_id": campaign_id,
                        "lead_name": lead_name[:160],
                        "phone_number": phone,
                        "dial_number": dial_number,
                        "company": company[:160],
                        "email": email[:255],
                        "note": note[:500],
                    },
                )
                if cursor.fetchone():
                    result.imported += 1
                else:
                    result.duplicates += 1
            except psycopg.Error as exc:
                result.invalid += 1
                result.failed_rows.append({"row": str(index), "reason": str(exc).splitlines()[0]})
    return result


def parse_lead_file(filename: str, content: bytes) -> tuple[list[dict[str, str]], list[str]]:
    name = filename.lower()
    if name.endswith(".xlsx"):
        rows = _parse_xlsx(content)
    elif name.endswith(".csv"):
        rows = _parse_delimited(content.decode("utf-8-sig", errors="replace"), ",")
    elif name.endswith(".tsv"):
        rows = _parse_delimited(content.decode("utf-8-sig", errors="replace"), "\t")
    else:
        rows = _parse_text(content.decode("utf-8-sig", errors="replace"))
    return rows, _columns(rows)


def parse_pasted_leads(text: str) -> tuple[list[dict[str, str]], list[str]]:
    rows = _parse_text(text)
    return rows, _columns(rows)


def fetch_google_sheet_csv(url: str) -> tuple[list[dict[str, str]], list[str]]:
    csv_url = _google_sheet_csv_url(url)
    with request.urlopen(csv_url, timeout=12) as response:
        body = response.read().decode("utf-8-sig", errors="replace")
    rows = _parse_delimited(body, ",")
    return rows, _columns(rows)


def detect_phone_column(columns: list[str], rows: list[dict[str, str]] | None = None) -> str:
    header_scores = {
        "phone": 8,
        "mobile": 8,
        "cell": 7,
        "contact": 5,
        "msisdn": 8,
        "telephone": 8,
        "tel": 5,
        "number": 3,
    }
    best_column = ""
    best_score = 0
    for column in columns:
        lower = column.lower().replace("_", " ").replace("-", " ")
        score = sum(weight for word, weight in header_scores.items() if word in lower)
        if rows:
            for row in rows[:25]:
                value = str(row.get(column) or "")
                if _normalize_phone(value):
                    score += 10
        if score > best_score:
            best_column = column
            best_score = score
    if best_score >= 8:
        return best_column
    return ""


def _clean_name(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip())


def _normalize_campaign(row: dict) -> dict:
    campaign = dict(row)
    campaign["need_to_call_count"] = max(
        0,
        int(campaign.get("lead_count") or 0)
        - int(campaign.get("successful_count") or 0)
        - int(campaign.get("failed_count") or 0)
        - int(campaign.get("invalid_count") or 0),
    )
    for key in ("assigned_users", "assigned_groups"):
        value = campaign.get(key) or []
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except json.JSONDecodeError:
                value = []
        campaign[key] = value
    return campaign


def _json_list(value) -> list[str]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            value = []
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _online_extensions(connection: psycopg.Connection) -> set[str]:
    snapshot = collect_status_snapshot(connection)
    rows = snapshot.get("extensions") if isinstance(snapshot, dict) else []
    if not isinstance(rows, list):
        return set()
    return {
        str(row.get("extension"))
        for row in rows
        if isinstance(row, dict) and row.get("status") == "Online" and str(row.get("extension") or "").strip()
    }


def _busy_extensions() -> set[str]:
    try:
        from app.services.ami import ami_command

        output = ami_command("core show channels concise")
    except Exception:
        return set()
    busy: set[str] = set()
    for line in output.splitlines():
        channel = line.split("!", 1)[0]
        match = re.match(r"PJSIP/(\d+)-", channel)
        if match:
            busy.add(match.group(1))
    return busy


def _auto_dialer_loop() -> None:
    settings = get_settings()
    while not _AUTODIALER_STOP.wait(3):
        try:
            with psycopg.connect(settings.db_dsn, autocommit=True) as connection:
                run_auto_dialer_tick(connection)
        except Exception:
            time.sleep(3)


def _running_auto_campaigns(connection: psycopg.Connection) -> list[dict]:
    with connection.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT campaign.*
            FROM autodialer_campaigns campaign
            WHERE campaign.status = 'running'
              AND campaign.dialing_mode = 'auto'
              AND EXISTS (
                  SELECT 1
                  FROM autodialer_leads lead
                  WHERE lead.campaign_id = campaign.id
                    AND lead.status = 'ready'
              )
              AND NOT EXISTS (
                  SELECT 1
                  FROM autodialer_leads recent
                  WHERE recent.campaign_id = campaign.id
                    AND recent.last_call_at > NOW() - (campaign.next_call_wait_seconds || ' seconds')::interval
              )
            ORDER BY campaign.updated_at ASC, campaign.id ASC
            """
        )
        return [_normalize_campaign(row) for row in cursor.fetchall()]


def _claim_next_ready_lead(connection: psycopg.Connection, campaign_id: int) -> dict | None:
    with connection.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            UPDATE autodialer_leads lead
            SET status = 'calling',
                updated_at = NOW()
            WHERE lead.id = (
                SELECT candidate.id
                FROM autodialer_leads candidate
                JOIN autodialer_campaigns campaign ON campaign.id = candidate.campaign_id
                WHERE candidate.campaign_id = %(campaign_id)s
                  AND candidate.status = 'ready'
                  AND NOT EXISTS (
                      SELECT 1
                      FROM autodialer_leads recent
                      WHERE recent.campaign_id = campaign.id
                        AND recent.last_call_at > NOW() - (campaign.next_call_wait_seconds || ' seconds')::interval
                  )
                ORDER BY candidate.last_call_at NULLS FIRST, candidate.created_at ASC, candidate.id ASC
                LIMIT 1
            )
            RETURNING lead.id, lead.phone_number, lead.dial_number
            """,
            {"campaign_id": campaign_id},
        )
        return cursor.fetchone()


def _mark_lead_called(connection: psycopg.Connection, campaign_id: int, lead_id: int, result: str) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            UPDATE autodialer_leads
            SET status = 'called',
                attempts = attempts + 1,
                last_call_at = NOW(),
                last_result = %(result)s,
                updated_at = NOW()
            WHERE id = %(lead_id)s AND campaign_id = %(campaign_id)s
            """,
            {"campaign_id": campaign_id, "lead_id": lead_id, "result": result[:80]},
        )


def _release_claimed_lead(connection: psycopg.Connection, campaign_id: int, lead_id: int, reason: str) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            UPDATE autodialer_leads
            SET status = 'ready',
                last_result = %(reason)s,
                updated_at = NOW()
            WHERE id = %(lead_id)s AND campaign_id = %(campaign_id)s
            """,
            {"campaign_id": campaign_id, "lead_id": lead_id, "reason": reason[:80]},
        )


def _mark_lead_invalid(connection: psycopg.Connection, campaign_id: int, lead_id: int, reason: str) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            UPDATE autodialer_leads
            SET status = 'invalid',
                last_result = %(reason)s,
                updated_at = NOW()
            WHERE id = %(lead_id)s AND campaign_id = %(campaign_id)s
            """,
            {"campaign_id": campaign_id, "lead_id": lead_id, "reason": reason[:80]},
        )


def _finish_campaign_if_empty(connection: psycopg.Connection, campaign_id: int) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            UPDATE autodialer_campaigns campaign
            SET status = 'finished',
                updated_at = NOW()
            WHERE campaign.id = %(campaign_id)s
              AND campaign.status = 'running'
              AND NOT EXISTS (
                  SELECT 1
                  FROM autodialer_leads lead
                  WHERE lead.campaign_id = campaign.id
                    AND lead.status = 'ready'
              )
            """,
            {"campaign_id": campaign_id},
        )


def _finish_completed_auto_campaigns(connection: psycopg.Connection) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            UPDATE autodialer_campaigns campaign
            SET status = 'finished',
                updated_at = NOW()
            WHERE campaign.status = 'running'
              AND campaign.dialing_mode = 'auto'
              AND NOT EXISTS (
                  SELECT 1
                  FROM autodialer_leads lead
                  WHERE lead.campaign_id = campaign.id
                    AND lead.status = 'ready'
              )
            """
        )




def _normalize_phone(value: str) -> str:
    display_number, _ = _normalize_phone_pair(value, "+880")
    return display_number


def _normalize_phone_pair(value: str, dialing_region: str = "") -> tuple[str, str]:
    cleaned = re.sub(r"[^0-9+]", "", value.strip())
    if cleaned.startswith("00"):
        cleaned = f"+{cleaned[2:]}"
    digits = re.sub(r"\D", "", cleaned)
    if len(digits) < 7 or len(digits) > 16:
        return "", ""
    if cleaned.startswith("+"):
        dial_digits = digits
        display_number = f"+{digits}"
    else:
        dial_digits = digits
        display_number = cleaned
    return display_number, dial_digits


def _find_phone_value(row: dict[str, str]) -> str:
    preferred = detect_phone_column(list(row.keys()), [row])
    if preferred and row.get(preferred):
        return str(row.get(preferred) or "")
    for value in row.values():
        candidate = str(value or "")
        if _normalize_phone(candidate):
            return candidate
    return ""


def _unique_lead_name(cursor, campaign_id: int, lead_name: str, phone: str) -> str:
    base_name = _clean_name(lead_name)[:140] or phone
    cursor.execute(
        """
        SELECT 1
        FROM autodialer_leads
        WHERE campaign_id = %(campaign_id)s
          AND lower(lead_name) = lower(%(lead_name)s)
        LIMIT 1
        """,
        {"campaign_id": campaign_id, "lead_name": base_name},
    )
    if not cursor.fetchone():
        return base_name
    suffix = re.sub(r"\D", "", phone)[-4:] or "lead"
    unique_name = f"{base_name} {suffix}"[:160]
    cursor.execute(
        """
        SELECT 1
        FROM autodialer_leads
        WHERE campaign_id = %(campaign_id)s
          AND lower(lead_name) = lower(%(lead_name)s)
        LIMIT 1
        """,
        {"campaign_id": campaign_id, "lead_name": unique_name},
    )
    if not cursor.fetchone():
        return unique_name
    timestamp = datetime.utcnow().strftime("%H%M%S")
    return f"{base_name} {timestamp}"[:160]


def _field(row: dict[str, str], column: str) -> str:
    if not column:
        return ""
    return str(row.get(column) or "").strip()


def _columns(rows: list[dict[str, str]]) -> list[str]:
    columns: list[str] = []
    for row in rows:
        for key in row:
            if key not in columns:
                columns.append(key)
    return columns


def _parse_delimited(text: str, delimiter: str) -> list[dict[str, str]]:
    sample = text[:2048]
    nonempty_lines = [line.strip() for line in text.splitlines() if line.strip()]
    try:
        dialect = csv.Sniffer().sniff(sample)
    except csv.Error:
        dialect = csv.excel
        dialect.delimiter = delimiter
    reader = csv.DictReader(io.StringIO(text), dialect=dialect)
    if not reader.fieldnames:
        return _parse_text(text)
    rows = [
        {str(key or "").strip(): str(value or "").strip() for key, value in row.items() if str(key or "").strip()}
        for row in reader
        if any(str(value or "").strip() for value in row.values())
    ]
    if not rows and any(_normalize_phone(str(field or "")) for field in reader.fieldnames):
        return _parse_text(text)
    if not rows and len(nonempty_lines) == 1:
        return _parse_text(text)
    return rows


def _parse_text(text: str) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for line in text.splitlines():
        cleaned = line.strip()
        if not cleaned:
            continue
        parts = [part.strip() for part in re.split(r"[,|\t]", cleaned) if part.strip()]
        if len(parts) >= 2:
            rows.append({"lead_name": parts[0], "phone_number": parts[1], "note": " ".join(parts[2:])})
        else:
            rows.append({"phone_number": cleaned})
    return rows


def _parse_xlsx(content: bytes) -> list[dict[str, str]]:
    with zipfile.ZipFile(io.BytesIO(content)) as workbook:
        shared_strings = _xlsx_shared_strings(workbook)
        sheet_name = _xlsx_first_sheet_name(workbook)
        root = ElementTree.fromstring(workbook.read(sheet_name))
    namespace = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    table: list[list[str]] = []
    for row in root.findall(".//x:sheetData/x:row", namespace):
        values: list[str] = []
        for cell in row.findall("x:c", namespace):
            cell_ref = cell.attrib.get("r", "")
            column_index = _xlsx_column_index(cell_ref)
            while len(values) < column_index:
                values.append("")
            value_node = cell.find("x:v", namespace)
            raw_value = value_node.text if value_node is not None else ""
            if cell.attrib.get("t") == "s" and raw_value.isdigit():
                values.append(shared_strings[int(raw_value)] if int(raw_value) < len(shared_strings) else "")
            else:
                values.append(raw_value or "")
        if any(value.strip() for value in values):
            table.append(values)
    if not table:
        return []
    headers = [header.strip() or f"column_{index + 1}" for index, header in enumerate(table[0])]
    return [
        {headers[index]: value.strip() for index, value in enumerate(row) if index < len(headers)}
        for row in table[1:]
        if any(value.strip() for value in row)
    ]


def _xlsx_shared_strings(workbook: zipfile.ZipFile) -> list[str]:
    try:
        root = ElementTree.fromstring(workbook.read("xl/sharedStrings.xml"))
    except KeyError:
        return []
    namespace = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    values: list[str] = []
    for item in root.findall("x:si", namespace):
        values.append("".join(text.text or "" for text in item.findall(".//x:t", namespace)))
    return values


def _xlsx_first_sheet_name(workbook: zipfile.ZipFile) -> str:
    names = [name for name in workbook.namelist() if name.startswith("xl/worksheets/sheet") and name.endswith(".xml")]
    if not names:
        raise ValueError("XLSX file does not contain a worksheet.")
    return sorted(names)[0]


def _xlsx_column_index(cell_ref: str) -> int:
    letters = "".join(char for char in cell_ref if char.isalpha())
    index = 0
    for char in letters:
        index = index * 26 + (ord(char.upper()) - ord("A") + 1)
    return max(index - 1, 0)


def _google_sheet_csv_url(url: str) -> str:
    parsed = parse.urlparse(url.strip())
    if "docs.google.com" not in parsed.netloc or "/spreadsheets/" not in parsed.path:
        return url
    sheet_id = parsed.path.split("/d/", 1)[-1].split("/", 1)[0]
    query = parse.parse_qs(parsed.query)
    gid = (query.get("gid") or ["0"])[0]
    return f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv&gid={gid}"
