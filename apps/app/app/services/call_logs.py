from __future__ import annotations

import csv
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import quote

import psycopg
from psycopg.rows import dict_row

from app.core.settings import get_settings
from app.services.call_classification import (
    MISSED_DISPOSITIONS,
    abandoned_call_condition,
    callback_candidate_condition,
    customer_missed_call_condition,
)
from app.services.date_ranges import parse_date_bound


CALL_LOG_CATEGORIES = {
    "all": "All Calls",
    "missed": "Missed Calls",
    "abandoned": "Abandoned Calls",
    "incoming": "Incoming Calls",
    "outgoing": "Outgoing Calls",
}
CDR_COLUMNS = [
    "calldate",
    "uniqueid",
    "linkedid",
    "src",
    "dst",
    "clid",
    "channel",
    "dstchannel",
    "lastapp",
    "lastdata",
    "duration",
    "billsec",
    "disposition",
    "amaflags",
    "recordingfile",
    "direction",
    "trunk_name",
    "route_name",
    "queue_name",
    "ivr_name",
    "caller_extension",
    "callee_extension",
]


def sync_cdr_from_asterisk(connection: psycopg.Connection) -> dict[str, int]:
    settings = get_settings()
    cdr_path = Path(settings.cdr_custom_file)
    if not cdr_path.exists():
        return {"imported": 0, "updated": 0}

    imported = 0
    updated = 0
    with cdr_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.reader(handle)
        with connection.cursor() as cursor:
            for row in reader:
                if not row:
                    continue
                padded = row[: len(CDR_COLUMNS)] + [""] * max(0, len(CDR_COLUMNS) - len(row))
                values = dict(zip(CDR_COLUMNS, padded, strict=False))
                uniqueid = (values.get("uniqueid") or "").strip()
                if not uniqueid:
                    continue
                values["calldate"] = _parse_datetime(values.get("calldate"))
                values["duration"] = _parse_int(values.get("duration"))
                values["billsec"] = _parse_int(values.get("billsec"))
                values["uniqueid"] = uniqueid
                values["linkedid"] = (values.get("linkedid") or uniqueid).strip() or uniqueid
                cursor.execute(
                    """
                    INSERT INTO cdr_raw (
                        calldate, uniqueid, linkedid, src, dst, clid, channel, dstchannel, lastapp, lastdata,
                        duration, billsec, disposition, amaflags, recordingfile, direction, trunk_name,
                        route_name, queue_name, ivr_name, caller_extension, callee_extension
                    ) VALUES (
                        %(calldate)s, %(uniqueid)s, %(linkedid)s, %(src)s, %(dst)s, %(clid)s, %(channel)s, %(dstchannel)s, %(lastapp)s, %(lastdata)s,
                        %(duration)s, %(billsec)s, %(disposition)s, %(amaflags)s, %(recordingfile)s, %(direction)s, %(trunk_name)s,
                        %(route_name)s, %(queue_name)s, %(ivr_name)s, %(caller_extension)s, %(callee_extension)s
                    )
                    ON CONFLICT (uniqueid) DO UPDATE
                    SET
                        calldate = EXCLUDED.calldate,
                        linkedid = EXCLUDED.linkedid,
                        src = EXCLUDED.src,
                        dst = EXCLUDED.dst,
                        clid = EXCLUDED.clid,
                        channel = EXCLUDED.channel,
                        dstchannel = EXCLUDED.dstchannel,
                        lastapp = EXCLUDED.lastapp,
                        lastdata = EXCLUDED.lastdata,
                        duration = EXCLUDED.duration,
                        billsec = EXCLUDED.billsec,
                        disposition = EXCLUDED.disposition,
                        amaflags = EXCLUDED.amaflags,
                        recordingfile = EXCLUDED.recordingfile,
                        direction = EXCLUDED.direction,
                        trunk_name = EXCLUDED.trunk_name,
                        route_name = EXCLUDED.route_name,
                        queue_name = EXCLUDED.queue_name,
                        ivr_name = EXCLUDED.ivr_name,
                        caller_extension = EXCLUDED.caller_extension,
                        callee_extension = EXCLUDED.callee_extension,
                        updated_at = NOW()
                    RETURNING (xmax = 0) AS inserted
                    """,
                    values,
                )
                inserted = cursor.fetchone()[0]
                if inserted:
                    imported += 1
                else:
                    updated += 1
    return {"imported": imported, "updated": updated}


def list_call_logs(
    connection: psycopg.Connection,
    *,
    search: str = "",
    direction: str = "all",
    category: str = "all",
    date_from: str | None = None,
    date_to: str | None = None,
    timezone_name: str = "UTC",
    limit: int = 250,
) -> dict[str, object]:
    sync_cdr_from_asterisk(connection)
    where = ["1=1"]
    params: dict[str, object] = {"limit": limit, "missed": list(MISSED_DISPOSITIONS)}
    search = search.strip()
    if search:
        params["search"] = f"%{search}%"
        where.append(
            """
            (
                COALESCE(NULLIF(caller_extension, ''), src, clid, '') ILIKE %(search)s OR
                COALESCE(NULLIF(callee_extension, ''), NULLIF(queue_name, ''), NULLIF(ivr_name, ''), dst, '') ILIKE %(search)s OR
                COALESCE(linkedid, uniqueid, '') ILIKE %(search)s OR
                COALESCE(route_name, '') ILIKE %(search)s OR
                COALESCE(trunk_name, '') ILIKE %(search)s
            )
            """
        )
    if direction != "all":
        params["direction"] = direction
        where.append("COALESCE(direction, 'unknown') = %(direction)s")
    if date_from:
        params["date_from"] = _date_bound(date_from, end_of_day=False, timezone_name=timezone_name)
        where.append("calldate >= %(date_from)s::timestamptz")
    if date_to:
        params["date_to"] = _date_bound(date_to, end_of_day=True, timezone_name=timezone_name)
        where.append("calldate <= %(date_to)s::timestamptz")

    category = category if category in CALL_LOG_CATEGORIES else "all"
    base_where_sql = " AND ".join(where)
    category_where = _call_log_category_condition(category)
    row_where = list(where)
    if category_where:
        row_where.append(category_where)
    where_sql = " AND ".join(row_where)
    with connection.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            f"""
            SELECT
                COUNT(*) AS all_calls,
                COALESCE(SUM(CASE WHEN {customer_missed_call_condition()} THEN 1 ELSE 0 END), 0) AS missed,
                COALESCE(SUM(CASE WHEN {abandoned_call_condition()} THEN 1 ELSE 0 END), 0) AS abandoned,
                COALESCE(SUM(CASE WHEN COALESCE(direction, 'unknown') = 'inbound' THEN 1 ELSE 0 END), 0) AS incoming,
                COALESCE(SUM(CASE WHEN COALESCE(direction, 'unknown') = 'outbound' THEN 1 ELSE 0 END), 0) AS outgoing
            FROM cdr_raw
            WHERE {base_where_sql}
            """,
            {k: v for k, v in params.items() if k != "limit"},
        )
        category_counts = dict(cursor.fetchone())
        category_counts["all"] = category_counts.pop("all_calls", 0)
        cursor.execute(
            f"""
            SELECT
                id,
                TO_CHAR(calldate, 'YYYY-MM-DD HH24:MI:SS') AS call_time,
                uniqueid,
                COALESCE(NULLIF(linkedid, ''), uniqueid) AS linkedid,
                COALESCE(NULLIF(caller_extension, ''), NULLIF(src, ''), NULLIF(clid, ''), 'unknown') AS caller,
                COALESCE(NULLIF(callee_extension, ''), NULLIF(queue_name, ''), NULLIF(ivr_name, ''), NULLIF(dst, ''), 'unknown') AS callee,
                COALESCE(direction, 'unknown') AS direction,
                trunk_name,
                route_name,
                queue_name,
                ivr_name,
                duration,
                billsec,
                disposition,
                CASE
                    WHEN {abandoned_call_condition()} THEN 'Abandoned'
                    WHEN {customer_missed_call_condition()} THEN 'Missed'
                    WHEN COALESCE(direction, 'unknown') = 'inbound' THEN 'Incoming'
                    WHEN COALESCE(direction, 'unknown') = 'outbound' THEN 'Outgoing'
                    ELSE INITCAP(COALESCE(direction, 'unknown'))
                END AS call_type,
                recordingfile,
                caller_extension,
                callee_extension
            FROM cdr_raw
            WHERE {where_sql}
            ORDER BY calldate DESC NULLS LAST, id DESC
            LIMIT %(limit)s
            """,
            params,
        )
        rows = list(cursor.fetchall())
        cursor.execute(
            f"""
            SELECT
                COUNT(*) AS total_calls,
                COALESCE(SUM(CASE WHEN COALESCE(direction, 'unknown') = 'inbound' THEN 1 ELSE 0 END), 0) AS total_inbound,
                COALESCE(SUM(CASE WHEN COALESCE(direction, 'unknown') = 'outbound' THEN 1 ELSE 0 END), 0) AS total_outbound,
                COALESCE(SUM(CASE WHEN COALESCE(direction, 'unknown') = 'internal' THEN 1 ELSE 0 END), 0) AS total_internal,
                COALESCE(SUM(CASE WHEN disposition = 'ANSWERED' THEN 1 ELSE 0 END), 0) AS total_answered,
                COALESCE(SUM(CASE WHEN {customer_missed_call_condition()} THEN 1 ELSE 0 END), 0) AS total_missed,
                COALESCE(SUM(duration), 0) AS total_duration,
                COALESCE(SUM(billsec), 0) AS total_billsec
            FROM cdr_raw
            WHERE {where_sql}
            """,
            {k: v for k, v in params.items() if k != "limit"},
        )
        summary = cursor.fetchone()
    return {
        "rows": [_with_recording_metadata(dict(row)) for row in rows],
        "summary": dict(summary),
        "category_counts": category_counts,
        "category": category,
        "categories": [
            {"key": key, "label": label, "count": category_counts.get(key, 0)}
            for key, label in CALL_LOG_CATEGORIES.items()
        ],
    }


def _call_log_category_condition(category: str) -> str | None:
    if category == "missed":
        return customer_missed_call_condition()
    if category == "abandoned":
        return abandoned_call_condition()
    if category == "incoming":
        return "COALESCE(direction, 'unknown') = 'inbound'"
    if category == "outgoing":
        return "COALESCE(direction, 'unknown') = 'outbound'"
    return None


def list_callback_worklist(
    connection: psycopg.Connection,
    *,
    search: str = "",
    open_only: bool = True,
    date_from: str | None = None,
    date_to: str | None = None,
    timezone_name: str = "UTC",
    limit: int = 500,
) -> dict[str, object]:
    sync_cdr_from_asterisk(connection)
    base_where = [
        callback_candidate_condition("c"),
        "COALESCE(NULLIF(c.src, ''), NULLIF(c.clid, ''), '') <> ''",
    ]
    params: dict[str, object] = {"missed": list(MISSED_DISPOSITIONS), "limit": limit}
    search = search.strip()
    if search:
        params["search"] = f"%{search}%"
        base_where.append("COALESCE(NULLIF(c.src, ''), NULLIF(c.clid, ''), '') ILIKE %(search)s")
    if date_from:
        params["date_from"] = _date_bound(date_from, end_of_day=False, timezone_name=timezone_name)
        base_where.append("c.calldate >= %(date_from)s::timestamptz")
    if date_to:
        params["date_to"] = _date_bound(date_to, end_of_day=True, timezone_name=timezone_name)
        base_where.append("c.calldate <= %(date_to)s::timestamptz")
    row_where = list(base_where)
    if open_only:
        row_where.append("COALESCE(cf.completed, FALSE) = FALSE")
        row_where.append(f"NOT EXISTS ({_later_answered_inbound_sql()})")
    row_where_sql = " AND ".join(row_where)
    summary_where_sql = " AND ".join(base_where)
    with connection.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            f"""
            SELECT DISTINCT ON (COALESCE(NULLIF(c.linkedid, ''), c.uniqueid))
                COALESCE(NULLIF(c.linkedid, ''), c.uniqueid) AS linkedid,
                TO_CHAR(c.calldate, 'YYYY-MM-DD HH24:MI:SS') AS call_time,
                COALESCE(NULLIF(c.src, ''), NULLIF(c.clid, ''), 'unknown') AS caller_number,
                COALESCE(NULLIF(c.callee_extension, ''), NULLIF(c.queue_name, ''), NULLIF(c.ivr_name, ''), NULLIF(c.dst, ''), '') AS target,
                c.route_name,
                c.queue_name,
                c.ivr_name,
                EXISTS ({_later_answered_inbound_sql()}) AS auto_resolved,
                CASE
                    WHEN COALESCE(NULLIF(c.queue_name, ''), '') <> '' AND c.disposition <> 'ANSWERED' THEN 'Queue Abandoned'
                    WHEN COALESCE(NULLIF(c.ivr_name, ''), '') <> '' AND COALESCE(NULLIF(c.callee_extension, ''), '') = '' THEN 'IVR Abandoned'
                    WHEN COALESCE(NULLIF(c.callee_extension, ''), '') <> '' AND c.disposition <> 'ANSWERED' THEN 'Missed Extension'
                    ELSE 'Missed Inbound'
                END AS callback_reason,
                CASE
                    WHEN COALESCE(cf.completed, FALSE) THEN 'done'
                    WHEN EXISTS ({_later_answered_inbound_sql()}) THEN 'answered_later'
                    WHEN COALESCE(NULLIF(cf.assigned_to, ''), '') <> '' THEN 'in_progress'
                    ELSE 'needs_callback'
                END AS followup_status,
                COALESCE(cf.completed, FALSE) AS completed,
                TO_CHAR(cf.completed_at, 'YYYY-MM-DD HH24:MI:SS') AS completed_at,
                cf.assigned_to,
                TO_CHAR(cf.assigned_at, 'YYYY-MM-DD HH24:MI:SS') AS assigned_at,
                cf.completed_by,
                cf.callback_number,
                cf.note
            FROM cdr_raw c
            LEFT JOIN callback_followups cf
              ON cf.linkedid = COALESCE(NULLIF(c.linkedid, ''), c.uniqueid)
            WHERE {row_where_sql}
            ORDER BY COALESCE(NULLIF(c.linkedid, ''), c.uniqueid),
                     c.calldate DESC NULLS LAST,
                     c.id DESC
            LIMIT %(limit)s
            """,
            params,
        )
        rows = [dict(row) for row in cursor.fetchall()]
        cursor.execute(
            f"""
            WITH callback_base AS (
                SELECT DISTINCT ON (COALESCE(NULLIF(c.linkedid, ''), c.uniqueid))
                    COALESCE(NULLIF(c.linkedid, ''), c.uniqueid) AS linkedid,
                    COALESCE(cf.completed, FALSE) AS completed,
                    cf.completed_at,
                    COALESCE(NULLIF(cf.assigned_to, ''), '') AS assigned_to,
                    EXISTS ({_later_answered_inbound_sql()}) AS auto_resolved
                FROM cdr_raw c
                LEFT JOIN callback_followups cf
                  ON cf.linkedid = COALESCE(NULLIF(c.linkedid, ''), c.uniqueid)
                WHERE {summary_where_sql}
                ORDER BY COALESCE(NULLIF(c.linkedid, ''), c.uniqueid),
                         c.calldate DESC NULLS LAST,
                         c.id DESC
            )
            SELECT
                COALESCE(SUM(CASE WHEN completed = FALSE AND auto_resolved = FALSE THEN 1 ELSE 0 END), 0) AS open_callbacks,
                COALESCE(SUM(CASE WHEN completed = FALSE AND auto_resolved = FALSE AND assigned_to <> '' THEN 1 ELSE 0 END), 0) AS in_progress,
                COALESCE(SUM(CASE WHEN completed = TRUE AND completed_at::date = CURRENT_DATE THEN 1 ELSE 0 END), 0) AS done_today,
                COALESCE(SUM(CASE WHEN completed = FALSE AND auto_resolved = TRUE THEN 1 ELSE 0 END), 0) AS answered_later
            FROM callback_base
            """,
            {k: v for k, v in params.items() if k != "limit"},
        )
        followup_summary = dict(cursor.fetchone())
    return {
        "rows": rows,
        "summary": followup_summary,
    }


def _later_answered_inbound_sql() -> str:
    return """
    SELECT 1
    FROM cdr_raw later
    WHERE COALESCE(later.direction, 'unknown') = 'inbound'
      AND later.disposition = 'ANSWERED'
      AND later.calldate > c.calldate
      AND COALESCE(NULLIF(later.src, ''), NULLIF(later.clid, ''), '') = COALESCE(NULLIF(c.src, ''), NULLIF(c.clid, ''), '')
    """


def update_callback_followup(
    connection: psycopg.Connection,
    linkedid: str,
    *,
    completed: bool,
    callback_number: str | None,
    note: str | None,
) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO callback_followups (linkedid, callback_number, status, completed, completed_at, note)
            VALUES (
                %(linkedid)s,
                %(callback_number)s,
                CASE WHEN %(completed)s THEN 'done' ELSE 'open' END,
                %(completed)s,
                CASE WHEN %(completed)s THEN NOW() ELSE NULL END,
                %(note)s
            )
            ON CONFLICT (linkedid) DO UPDATE
            SET
                callback_number = EXCLUDED.callback_number,
                status = EXCLUDED.status,
                completed = EXCLUDED.completed,
                completed_at = CASE WHEN EXCLUDED.completed THEN NOW() ELSE NULL END,
                note = EXCLUDED.note,
                updated_at = NOW()
            """,
            {
                "linkedid": linkedid,
                "callback_number": (callback_number or "").strip() or None,
                "completed": completed,
                "note": (note or "").strip() or None,
            },
        )


def take_callback_followup(
    connection: psycopg.Connection,
    linkedid: str,
    *,
    actor_username: str,
    callback_number: str | None = None,
) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO callback_followups (linkedid, callback_number, status, assigned_to, assigned_at, completed)
            VALUES (%(linkedid)s, %(callback_number)s, 'in_progress', %(actor_username)s, NOW(), FALSE)
            ON CONFLICT (linkedid) DO UPDATE
            SET
                callback_number = COALESCE(callback_followups.callback_number, EXCLUDED.callback_number),
                status = CASE WHEN callback_followups.completed THEN 'done' ELSE 'in_progress' END,
                assigned_to = CASE WHEN callback_followups.completed THEN callback_followups.assigned_to ELSE EXCLUDED.assigned_to END,
                assigned_at = CASE WHEN callback_followups.completed THEN callback_followups.assigned_at ELSE NOW() END,
                updated_at = NOW()
            """,
            {
                "linkedid": linkedid,
                "callback_number": (callback_number or "").strip() or None,
                "actor_username": actor_username,
            },
        )


def complete_callback_followup(
    connection: psycopg.Connection,
    linkedid: str,
    *,
    actor_username: str,
    note: str | None = None,
    callback_number: str | None = None,
) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO callback_followups (
                linkedid, callback_number, status, assigned_to, assigned_at, completed, completed_by, completed_at, note
            )
            VALUES (
                %(linkedid)s, %(callback_number)s, 'done', %(actor_username)s, NOW(), TRUE, %(actor_username)s, NOW(), %(note)s
            )
            ON CONFLICT (linkedid) DO UPDATE
            SET
                callback_number = COALESCE(EXCLUDED.callback_number, callback_followups.callback_number),
                status = 'done',
                completed = TRUE,
                completed_by = EXCLUDED.completed_by,
                completed_at = NOW(),
                note = COALESCE(EXCLUDED.note, callback_followups.note),
                assigned_to = COALESCE(callback_followups.assigned_to, EXCLUDED.assigned_to),
                assigned_at = COALESCE(callback_followups.assigned_at, EXCLUDED.assigned_at),
                updated_at = NOW()
            """,
            {
                "linkedid": linkedid,
                "callback_number": (callback_number or "").strip() or None,
                "actor_username": actor_username,
                "note": (note or "").strip() or None,
            },
        )


def resolve_recording_path(recordingfile: str | None) -> Path | None:
    settings = get_settings()
    normalized_name = (recordingfile or "").strip()
    if not normalized_name:
        return None
    candidate = (Path(settings.recordings_dir) / normalized_name).resolve()
    try:
        candidate.relative_to(Path(settings.recordings_dir).resolve())
    except ValueError:
        return None
    if not candidate.is_file() or candidate.stat().st_size <= 0:
        return None
    return candidate


def _with_recording_metadata(row: dict) -> dict:
    recording_path = resolve_recording_path(row.get("recordingfile"))
    if not recording_path:
        row["recording_available"] = False
        row["recording_url"] = None
        return row
    row["recordingfile"] = recording_path.name
    row["recording_available"] = True
    row["recording_url"] = f"/api/call-recordings/{quote(recording_path.name)}"
    return row


def _parse_datetime(value: str | None) -> datetime | None:
    cleaned = (value or "").strip()
    if not cleaned:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M:%S"):
        try:
            return datetime.strptime(cleaned, fmt)
        except ValueError:
            continue
    return None


def _date_bound(value: str, *, end_of_day: bool, timezone_name: str = "UTC") -> datetime | None:
    return parse_date_bound(value, end_of_day=end_of_day, timezone_name=timezone_name)


def _parse_int(value: str | None) -> int | None:
    cleaned = (value or "").strip()
    if not cleaned:
        return None
    try:
        return int(float(cleaned))
    except ValueError:
        return None
