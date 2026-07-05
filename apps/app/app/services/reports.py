from __future__ import annotations

import os
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

from app.core.settings import get_settings
from app.services.audit import list_admin_audit_entries
from app.services.backup import list_backup_files
from app.services.call_classification import (
    MISSED_DISPOSITIONS,
    abandoned_call_condition,
    customer_missed_call_condition,
)
from app.services.call_logs import (
    list_callback_worklist,
    sync_cdr_from_asterisk,
    visible_cdr_condition,
)
from app.services.date_ranges import DATE_RANGE_OPTIONS, parse_date_bound, resolve_date_range
from app.services.extensions import list_extensions
from app.services.live_events import live_event_hub
from app.services.queues import list_queues
from app.services.setup import get_system_settings
from app.services.trunks import list_trunks


REPORT_SECTIONS = [
    {"key": "overview", "label": "Overview"},
    {"key": "kpi", "label": "KPI"},
    {"key": "calls", "label": "Calls"},
    {"key": "follow-up", "label": "Follow Up"},
    {"key": "users", "label": "Users"},
    {"key": "queues", "label": "Queues"},
    {"key": "trunks", "label": "Trunks"},
    {"key": "system", "label": "System"},
]

REPORT_RANGES = [
    item for item in DATE_RANGE_OPTIONS if item["key"] != "custom"
]


def build_reports(
    connection: psycopg.Connection,
    *,
    section: str = "overview",
    range_key: str = "today",
    extension: str = "",
    date_from: str = "",
    date_to: str = "",
) -> dict[str, object]:
    sync_cdr_from_asterisk(connection)
    section = section if section in {item["key"] for item in REPORT_SECTIONS} else "overview"
    range_key = range_key if range_key in {item["key"] for item in DATE_RANGE_OPTIONS} else "today"
    timezone_name = str(get_system_settings(connection).get("timezone") or "UTC")
    resolved_range = resolve_date_range(range_key, date_from=date_from, date_to=date_to, default="today", timezone_name=timezone_name)
    range_key = resolved_range.key
    date_from = resolved_range.date_from
    date_to = resolved_range.date_to
    where_sql, params = _range_filter(range_key, date_from=date_from, date_to=date_to, timezone_name=timezone_name)
    params["missed"] = list(MISSED_DISPOSITIONS)

    calls = _call_summary(connection, where_sql, params)
    follow_up = _follow_up_summary(connection, date_from=date_from, date_to=date_to, timezone_name=timezone_name)
    users = _user_summary(connection, where_sql, params)
    user_detail = _user_detail_report(connection, where_sql, params, extension=extension)
    queues = _queue_summary(connection, where_sql, params)
    trunks = _trunk_summary(connection, where_sql, params)
    system = _system_summary(connection)
    recent_calls = _recent_calls(connection, where_sql, params, limit=20)
    hourly = _hourly_rows(connection, where_sql, params)
    daily = _daily_rows(connection, where_sql, params)
    dispositions = _disposition_rows(connection, where_sql, params)
    longest_calls = _longest_calls(connection, where_sql, params)
    audit_entries = list_admin_audit_entries(connection, limit=25)

    return {
        "active_section": section,
        "active_range": range_key,
        "date_from": date_from,
        "date_to": date_to,
        "sections": _sections_with_counts(section, calls, follow_up, users, queues, trunks, system),
        "ranges": DATE_RANGE_OPTIONS,
        "range_is_custom": resolved_range.is_custom,
        "calls": calls,
        "follow_up": follow_up,
        "users": users,
        "user_detail": user_detail,
        "queues": queues,
        "trunks": trunks,
        "system": system,
        "recent_calls": recent_calls,
        "hourly": hourly,
        "daily": daily,
        "dispositions": dispositions,
        "longest_calls": longest_calls,
        "audit_entries": audit_entries,
    }


def _range_filter(range_key: str, *, date_from: str = "", date_to: str = "", timezone_name: str = "UTC") -> tuple[str, dict[str, object]]:
    if range_key == "custom" and (date_from or date_to):
        where = []
        params: dict[str, object] = {}
        start = _parse_report_date(date_from, end_of_day=False, timezone_name=timezone_name)
        end = _parse_report_date(date_to, end_of_day=True, timezone_name=timezone_name)
        if start:
            where.append("calldate >= %(date_from)s")
            params["date_from"] = start
        if end:
            where.append("calldate <= %(date_to)s")
            params["date_to"] = end
        where.append(visible_cdr_condition())
        return " AND ".join(where), params
    if date_from or date_to:
        where = []
        params = {}
        start = _parse_report_date(date_from, end_of_day=False, timezone_name=timezone_name)
        end = _parse_report_date(date_to, end_of_day=True, timezone_name=timezone_name)
        if start:
            where.append("calldate >= %(date_from)s")
            params["date_from"] = start
        if end:
            where.append("calldate <= %(date_to)s")
            params["date_to"] = end
        where.append(visible_cdr_condition())
        return " AND ".join(where), params
    if range_key == "all":
        return visible_cdr_condition(), {}
    now = datetime.now(UTC)
    if range_key == "today":
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    elif range_key == "7d":
        start = now - timedelta(days=7)
    else:
        start = now - timedelta(days=30)
    return f"calldate >= %(date_from)s AND {visible_cdr_condition()}", {"date_from": start}


def _parse_report_date(value: str, *, end_of_day: bool, timezone_name: str = "UTC") -> datetime | None:
    return parse_date_bound(value, end_of_day=end_of_day, timezone_name=timezone_name)


def _call_summary(connection: psycopg.Connection, where_sql: str, params: dict[str, object]) -> dict[str, object]:
    with connection.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            f"""
            SELECT
                COUNT(*) AS total,
                COALESCE(SUM(CASE WHEN COALESCE(direction, 'unknown') = 'inbound' THEN 1 ELSE 0 END), 0) AS inbound,
                COALESCE(SUM(CASE WHEN COALESCE(direction, 'unknown') = 'outbound' THEN 1 ELSE 0 END), 0) AS outbound,
                COALESCE(SUM(CASE WHEN COALESCE(direction, 'unknown') = 'internal' THEN 1 ELSE 0 END), 0) AS internal,
                COALESCE(SUM(CASE WHEN disposition = 'ANSWERED' THEN 1 ELSE 0 END), 0) AS answered,
                COALESCE(SUM(CASE WHEN {customer_missed_call_condition()} THEN 1 ELSE 0 END), 0) AS missed,
                COALESCE(SUM(CASE WHEN {abandoned_call_condition()} THEN 1 ELSE 0 END), 0) AS abandoned,
                COALESCE(SUM(CASE WHEN COALESCE(NULLIF(recordingfile, ''), '') <> '' THEN 1 ELSE 0 END), 0) AS recorded,
                COALESCE(SUM(duration), 0) AS total_duration,
                COALESCE(SUM(billsec), 0) AS total_talk_time,
                COALESCE(ROUND(AVG(NULLIF(billsec, 0))), 0) AS avg_talk_time,
                COALESCE(MAX(calldate), NULL) AS last_call_at
            FROM cdr_raw
            WHERE {where_sql}
            """,
            params,
        )
        summary = dict(cursor.fetchone())

    total = int(summary["total"] or 0)
    inbound = int(summary["inbound"] or 0)
    answered = int(summary["answered"] or 0)
    missed = int(summary["missed"] or 0)
    abandoned = int(summary["abandoned"] or 0)
    summary["answer_rate"] = _percent(answered, total)
    summary["missed_rate"] = _percent(missed, inbound)
    summary["abandoned_rate"] = _percent(abandoned, inbound)
    summary["recorded_rate"] = _percent(summary.get("recorded"), total)
    summary["avg_talk_time_label"] = _duration_label(summary["avg_talk_time"])
    summary["total_talk_time_label"] = _duration_label(summary["total_talk_time"])
    summary["last_call_label"] = _time_label(summary.get("last_call_at"))
    return summary


def _follow_up_summary(
    connection: psycopg.Connection,
    *,
    date_from: str = "",
    date_to: str = "",
    timezone_name: str = "UTC",
) -> dict[str, object]:
    report = list_callback_worklist(
        connection,
        open_only=False,
        date_from=date_from,
        date_to=date_to,
        timezone_name=timezone_name,
        limit=25,
    )
    summary = dict(report["summary"])
    summary["rows"] = report["rows"][:10]
    summary["completion_rate"] = _percent(summary.get("done_today", 0), summary.get("open_callbacks", 0) + summary.get("done_today", 0))
    return summary


def _user_summary(connection: psycopg.Connection, where_sql: str, params: dict[str, object]) -> dict[str, object]:
    extensions = list_extensions(connection)
    enabled = [row for row in extensions if row.get("enabled")]
    live_status = _live_status_summary(len(extensions))

    with connection.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            f"""
            WITH per_extension AS (
                SELECT
                    COALESCE(NULLIF(caller_extension, ''), NULLIF(callee_extension, '')) AS extension,
                    COUNT(*) AS total_calls,
                    COALESCE(SUM(CASE WHEN disposition = 'ANSWERED' THEN 1 ELSE 0 END), 0) AS answered,
                    COALESCE(SUM(billsec), 0) AS talk_time
                FROM cdr_raw
                WHERE {where_sql}
                  AND COALESCE(NULLIF(caller_extension, ''), NULLIF(callee_extension, '')) <> ''
                GROUP BY COALESCE(NULLIF(caller_extension, ''), NULLIF(callee_extension, ''))
            )
            SELECT
                e.extension,
                e.display_name,
                COALESCE(p.total_calls, 0) AS total_calls,
                COALESCE(p.answered, 0) AS answered,
                COALESCE(p.talk_time, 0) AS talk_time
            FROM extensions e
            LEFT JOIN per_extension p ON p.extension = e.extension
            ORDER BY total_calls DESC, e.extension
            LIMIT 12
            """,
            params,
        )
        top_users = [dict(row) for row in cursor.fetchall()]

    for row in top_users:
        row["talk_time_label"] = _duration_label(row["talk_time"])
    return {
        "total": len(extensions),
        "enabled": len(enabled),
        "online": live_status["online"],
        "offline": live_status["offline"],
        "unknown": live_status["unknown"],
        "extensions": extensions,
        "top_users": top_users,
        "status_error": live_status["error"],
    }


def _user_detail_report(
    connection: psycopg.Connection,
    where_sql: str,
    params: dict[str, object],
    *,
    extension: str,
) -> dict[str, object]:
    extensions = list_extensions(connection)
    selected = (extension or "").strip()
    if not selected and extensions:
        selected = extensions[0]["extension"]
    selected_user = next((row for row in extensions if row["extension"] == selected), None)
    if not selected_user:
        selected_user = {"extension": selected, "display_name": selected or "No user selected"}

    user_params = {**params, "extension": selected}
    user_filter = _user_call_filter()
    with connection.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            f"""
            SELECT
                COUNT(*) AS total_calls,
                COALESCE(SUM(CASE WHEN {_user_incoming_filter()} THEN 1 ELSE 0 END), 0) AS incoming,
                COALESCE(SUM(CASE WHEN {_user_outgoing_filter()} THEN 1 ELSE 0 END), 0) AS outgoing,
                COALESCE(SUM(CASE WHEN disposition = 'ANSWERED' THEN 1 ELSE 0 END), 0) AS answered,
                COALESCE(SUM(CASE WHEN {_user_missed_filter()} THEN 1 ELSE 0 END), 0) AS missed,
                COALESCE(SUM(billsec), 0) AS talk_time,
                COALESCE(ROUND(AVG(NULLIF(billsec, 0))), 0) AS avg_talk_time
            FROM cdr_raw
            WHERE {where_sql}
              AND {user_filter}
            """,
            user_params,
        )
        summary = dict(cursor.fetchone())
        cursor.execute(
            f"""
            SELECT
                TO_CHAR(calldate::date, 'YYYY-MM-DD') AS day,
                COUNT(*) AS total_calls,
                COALESCE(SUM(CASE WHEN {_user_incoming_filter()} THEN 1 ELSE 0 END), 0) AS incoming,
                COALESCE(SUM(CASE WHEN {_user_outgoing_filter()} THEN 1 ELSE 0 END), 0) AS outgoing,
                COALESCE(SUM(CASE WHEN disposition = 'ANSWERED' THEN 1 ELSE 0 END), 0) AS answered,
                COALESCE(SUM(CASE WHEN {_user_missed_filter()} THEN 1 ELSE 0 END), 0) AS missed,
                COALESCE(SUM(billsec), 0) AS talk_time,
                COALESCE(ROUND(AVG(NULLIF(billsec, 0))), 0) AS avg_talk_time
            FROM cdr_raw
            WHERE {where_sql}
              AND {user_filter}
              AND calldate IS NOT NULL
            GROUP BY calldate::date
            ORDER BY calldate::date DESC
            LIMIT 31
            """,
            user_params,
        )
        daily = [dict(row) for row in cursor.fetchall()]
        cursor.execute(
            f"""
            SELECT
                TO_CHAR(calldate, 'YYYY-MM-DD HH24:MI:SS') AS call_time,
                COALESCE(NULLIF(src, ''), NULLIF(clid, ''), 'unknown') AS caller,
                COALESCE(NULLIF(dst, ''), NULLIF(callee_extension, ''), 'unknown') AS callee,
                CASE WHEN {_user_outgoing_filter()} THEN 'Outgoing' ELSE 'Incoming' END AS direction,
                disposition,
                billsec
            FROM cdr_raw
            WHERE {where_sql}
              AND {user_filter}
            ORDER BY calldate DESC NULLS LAST, id DESC
            LIMIT 12
            """,
            user_params,
        )
        recent = [dict(row) for row in cursor.fetchall()]

    total = int(summary.get("total_calls") or 0)
    incoming = int(summary.get("incoming") or 0)
    answered = int(summary.get("answered") or 0)
    missed = int(summary.get("missed") or 0)
    summary["answer_rate"] = _percent(answered, total)
    summary["missed_rate"] = _percent(missed, incoming)
    summary["talk_time_label"] = _duration_label(summary.get("talk_time"))
    summary["avg_talk_time_label"] = _duration_label(summary.get("avg_talk_time"))
    for row in daily:
        row["answer_rate"] = _percent(row.get("answered"), row.get("total_calls"))
        row["talk_time_label"] = _duration_label(row.get("talk_time"))
        row["avg_talk_time_label"] = _duration_label(row.get("avg_talk_time"))
    for row in recent:
        row["talk_time_label"] = _duration_label(row.get("billsec"))
    return {
        "selected_extension": selected,
        "selected_user": selected_user,
        "extensions": extensions,
        "summary": summary,
        "daily": daily,
        "recent": recent,
    }


def _user_call_filter() -> str:
    return f"({_user_incoming_filter()} OR {_user_outgoing_filter()})"


def _user_incoming_filter() -> str:
    return """
    COALESCE(direction, 'unknown') = 'inbound'
    AND (
        COALESCE(NULLIF(callee_extension, ''), '') = %(extension)s
        OR COALESCE(NULLIF(dst, ''), '') = %(extension)s
    )
    """


def _user_outgoing_filter() -> str:
    return """
    COALESCE(direction, 'unknown') = 'outbound'
    AND (
        COALESCE(NULLIF(caller_extension, ''), '') = %(extension)s
        OR COALESCE(NULLIF(src, ''), '') = %(extension)s
    )
    """


def _user_missed_filter() -> str:
    return f"""
    {_user_incoming_filter()}
    AND disposition = ANY(%(missed)s)
    """


def _queue_summary(connection: psycopg.Connection, where_sql: str, params: dict[str, object]) -> dict[str, object]:
    queues = list_queues(connection)
    with connection.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            f"""
            SELECT
                COALESCE(NULLIF(queue_name, ''), NULLIF(lastdata, ''), 'No queue') AS queue_name,
                COUNT(*) AS total_calls,
                COALESCE(SUM(CASE WHEN disposition = 'ANSWERED' THEN 1 ELSE 0 END), 0) AS answered,
                COALESCE(SUM(CASE WHEN disposition = ANY(%(missed)s) THEN 1 ELSE 0 END), 0) AS missed,
                COALESCE(SUM(CASE WHEN {abandoned_call_condition()} THEN 1 ELSE 0 END), 0) AS abandoned,
                COALESCE(SUM(CASE WHEN disposition = 'ANSWERED' AND GREATEST(duration - billsec, 0) <= 30 THEN 1 ELSE 0 END), 0) AS sla_answered,
                COALESCE(ROUND(AVG(NULLIF(duration - billsec, 0))), 0) AS avg_wait
            FROM cdr_raw
            WHERE {where_sql}
              AND (COALESCE(NULLIF(queue_name, ''), '') <> '' OR lastapp = 'Queue')
            GROUP BY COALESCE(NULLIF(queue_name, ''), NULLIF(lastdata, ''), 'No queue')
            ORDER BY total_calls DESC, queue_name
            LIMIT 12
            """,
            params,
        )
        rows = [dict(row) for row in cursor.fetchall()]

    for row in rows:
        row["answer_rate"] = _percent(row["answered"], row["total_calls"])
        row["abandoned_rate"] = _percent(row["abandoned"], row["total_calls"])
        row["sla_rate"] = _percent(row["sla_answered"], row["total_calls"])
        row["avg_wait_label"] = _duration_label(row["avg_wait"])
    return {
        "configured": len(queues),
        "enabled": len([queue for queue in queues if queue.get("enabled")]),
        "rows": rows,
    }


def _trunk_summary(connection: psycopg.Connection, where_sql: str, params: dict[str, object]) -> dict[str, object]:
    configured = list_trunks(connection)
    with connection.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            f"""
            SELECT
                COALESCE(NULLIF(trunk_name, ''), 'No trunk') AS trunk_name,
                COUNT(*) AS total_calls,
                COALESCE(SUM(CASE WHEN COALESCE(direction, 'unknown') = 'inbound' THEN 1 ELSE 0 END), 0) AS inbound,
                COALESCE(SUM(CASE WHEN COALESCE(direction, 'unknown') = 'outbound' THEN 1 ELSE 0 END), 0) AS outbound,
                COALESCE(SUM(CASE WHEN disposition = 'ANSWERED' THEN 1 ELSE 0 END), 0) AS answered,
                COALESCE(SUM(CASE WHEN disposition <> 'ANSWERED' THEN 1 ELSE 0 END), 0) AS failed,
                COALESCE(SUM(billsec), 0) AS talk_time,
                COALESCE(ROUND(AVG(NULLIF(billsec, 0))), 0) AS avg_talk_time,
                MAX(calldate) AS last_call_at
            FROM cdr_raw
            WHERE {where_sql}
              AND COALESCE(NULLIF(trunk_name, ''), '') <> ''
            GROUP BY COALESCE(NULLIF(trunk_name, ''), 'No trunk')
            ORDER BY total_calls DESC, trunk_name
            LIMIT 20
            """,
            params,
        )
        rows = [dict(row) for row in cursor.fetchall()]
    for row in rows:
        row["answer_rate"] = _percent(row["answered"], row["total_calls"])
        row["failure_rate"] = _percent(row["failed"], row["total_calls"])
        row["talk_time_label"] = _duration_label(row.get("talk_time"))
        row["avg_talk_time_label"] = _duration_label(row.get("avg_talk_time"))
        row["last_call_label"] = _time_label(row.get("last_call_at"))
    return {
        "configured": len(configured),
        "enabled": len([trunk for trunk in configured if trunk.get("enabled")]),
        "rows": rows,
    }


def _system_summary(connection: psycopg.Connection) -> dict[str, object]:
    settings = get_settings()
    trunks = list_trunks(connection)
    live_status = _live_status_summary(0)
    recordings = _folder_report(Path(settings.recordings_dir), pattern="**/*")
    voicemail = _voicemail_report(Path(settings.voicemail_spool_dir))
    backups = _backup_report()
    runtime_disk = _disk_report(Path(settings.runtime_dir))

    with connection.cursor(row_factory=dict_row) as cursor:
        cursor.execute(f"SELECT MAX(calldate) AS last_cdr, COUNT(*) AS cdr_rows FROM cdr_raw WHERE {visible_cdr_condition()}")
        cdr = dict(cursor.fetchone())
        cursor.execute("SELECT MAX(eventtime) AS last_cel, COUNT(*) AS cel_rows FROM cel_raw")
        cel = dict(cursor.fetchone())
        cursor.execute("SELECT pg_database_size(current_database()) AS database_size")
        database = dict(cursor.fetchone())
        cursor.execute(
            """
            SELECT
                COALESCE(SUM(CASE WHEN event_type = 'auth.login_failed' THEN 1 ELSE 0 END), 0) AS failed_logins,
                COALESCE(SUM(CASE WHEN event_type = 'auth.login' THEN 1 ELSE 0 END), 0) AS admin_logins,
                COALESCE(SUM(CASE WHEN event_type LIKE 'backup.%%' THEN 1 ELSE 0 END), 0) AS backup_events,
                COALESCE(SUM(CASE WHEN event_type LIKE 'smtp.%%' THEN 1 ELSE 0 END), 0) AS smtp_events,
                MAX(created_at) AS last_admin_event
            FROM admin_audit_log
            WHERE created_at >= NOW() - INTERVAL '7 days'
            """
        )
        security = dict(cursor.fetchone())
        cursor.execute(
            """
            SELECT COUNT(*) AS dead_letters, MAX(last_attempt_at) AS last_api_push_error
            FROM api_push_dead_letters
            WHERE resolved = FALSE
            """
        )
        api_push = dict(cursor.fetchone())

    cdr_ok = bool(cdr.get("last_cdr"))
    cel_ok = bool(cel.get("last_cel"))
    warnings = []
    if live_status["error"]:
        warnings.append("Live status is not ready")
    if not cdr_ok:
        warnings.append("No CDR records yet")
    if not cel_ok:
        warnings.append("No CEL records yet")
    if int(api_push.get("dead_letters") or 0) > 0:
        warnings.append("API push has failed deliveries")
    if not backups["count"]:
        warnings.append("No backup snapshots")
    if not recordings["writable"]:
        warnings.append("Recording folder is not writable")
    if not voicemail["writable"]:
        warnings.append("Voicemail folder is not writable")
    status_label = "Healthy" if not warnings else "Needs Check"
    return {
        "status": status_label,
        "status_class": "success" if status_label == "Healthy" else "warning",
        "warnings": warnings,
        "extensions_online": live_status["online"],
        "trunks_total": len(trunks),
        "trunks_enabled": len([trunk for trunk in trunks if trunk.get("enabled")]),
        "trunks_disabled": len([trunk for trunk in trunks if not trunk.get("enabled")]),
        "cdr_rows": cdr.get("cdr_rows", 0),
        "cel_rows": cel.get("cel_rows", 0),
        "last_cdr_label": _time_label(cdr.get("last_cdr")),
        "last_cel_label": _time_label(cel.get("last_cel")),
        "cdr_status": "Working" if cdr_ok else "No data",
        "cel_status": "Working" if cel_ok else "No data",
        "voicemail_count": voicemail["messages"],
        "voicemail": voicemail,
        "recordings": recordings,
        "backups": backups,
        "runtime_disk": runtime_disk,
        "database_size_label": _bytes_label(database.get("database_size")),
        "security": {
            **security,
            "last_admin_event_label": _time_label(security.get("last_admin_event")),
        },
        "api_push": {
            **api_push,
            "last_api_push_error_label": _time_label(api_push.get("last_api_push_error")),
        },
        "status_error": live_status["error"],
        "health_checks": _system_health_checks(status_label, live_status, cdr_ok, cel_ok, trunks, recordings, voicemail, backups, api_push),
        "data_checks": _data_health_checks(cdr, cel, recordings, voicemail, backups, runtime_disk, database),
        "security_checks": _security_health_checks(security, api_push),
    }


def _system_health_checks(
    status_label: str,
    live_status: dict[str, object],
    cdr_ok: bool,
    cel_ok: bool,
    trunks: list[dict],
    recordings: dict[str, object],
    voicemail: dict[str, object],
    backups: dict[str, object],
    api_push: dict[str, object],
) -> list[dict[str, str]]:
    return [
        _check_item("PBX status", status_label, "success" if status_label == "Healthy" else "warning"),
        _check_item("Live phones", f"{live_status.get('online', 0)} online", "success" if not live_status.get("error") else "warning"),
        _check_item("Trunks", f"{len([trunk for trunk in trunks if trunk.get('enabled')])}/{len(trunks)} enabled", "success" if trunks else "warning"),
        _check_item("CDR call data", "Working" if cdr_ok else "No records yet", "success" if cdr_ok else "warning"),
        _check_item("CEL event data", "Working" if cel_ok else "No records yet", "success" if cel_ok else "warning"),
        _check_item("Recordings folder", "Writable" if recordings["writable"] else "Needs check", "success" if recordings["writable"] else "danger"),
        _check_item("Voicemail folder", "Writable" if voicemail["writable"] else "Needs check", "success" if voicemail["writable"] else "danger"),
        _check_item("Backups", f"{backups['count']} snapshots", "success" if backups["count"] else "warning"),
        _check_item("API push errors", f"{api_push.get('dead_letters', 0)} failed", "danger" if api_push.get("dead_letters") else "success"),
    ]


def _data_health_checks(
    cdr: dict[str, object],
    cel: dict[str, object],
    recordings: dict[str, object],
    voicemail: dict[str, object],
    backups: dict[str, object],
    runtime_disk: dict[str, object],
    database: dict[str, object],
) -> list[dict[str, str]]:
    return [
        _check_item("Last CDR", _time_label(cdr.get("last_cdr")), "success" if cdr.get("last_cdr") else "warning"),
        _check_item("Last CEL", _time_label(cel.get("last_cel")), "success" if cel.get("last_cel") else "warning"),
        _check_item("Database size", _bytes_label(database.get("database_size")), "success"),
        _check_item("Recordings", f"{recordings['count']} files / {recordings['size_label']}", "success" if recordings["writable"] else "danger"),
        _check_item("Voicemail", f"{voicemail['messages']} messages / {voicemail['size_label']}", "success" if voicemail["writable"] else "danger"),
        _check_item("Backups size", backups["size_label"], "success" if backups["count"] else "warning"),
        _check_item("Disk free", runtime_disk["free_label"], "success" if runtime_disk["free_percent"] >= 15 else "warning"),
    ]


def _security_health_checks(security: dict[str, object], api_push: dict[str, object]) -> list[dict[str, str]]:
    failed_logins = int(security.get("failed_logins") or 0)
    dead_letters = int(api_push.get("dead_letters") or 0)
    return [
        _check_item("Admin logins", str(security.get("admin_logins") or 0), "success"),
        _check_item("Failed logins", str(failed_logins), "warning" if failed_logins else "success"),
        _check_item("Backup changes", str(security.get("backup_events") or 0), "success"),
        _check_item("SMTP changes", str(security.get("smtp_events") or 0), "success"),
        _check_item("Last admin event", _time_label(security.get("last_admin_event")), "success" if security.get("last_admin_event") else "warning"),
        _check_item("API push failed deliveries", str(dead_letters), "danger" if dead_letters else "success"),
        _check_item("Last API push error", _time_label(api_push.get("last_api_push_error")), "warning" if dead_letters else "success"),
    ]


def _check_item(label: str, value: str, tone: str) -> dict[str, str]:
    return {"label": label, "value": value, "tone": tone}


def _backup_report() -> dict[str, object]:
    try:
        backups = list_backup_files()
    except Exception:
        backups = []
    size = sum(int(item.get("size_bytes") or 0) for item in backups)
    latest = backups[0] if backups else {}
    return {
        "count": len(backups),
        "size_bytes": size,
        "size_label": _bytes_label(size),
        "latest_label": latest.get("exported_at") or "No backup",
        "latest_name": latest.get("file_name") or "",
    }


def _folder_report(path: Path, *, pattern: str) -> dict[str, object]:
    files = _safe_files(path, pattern)
    size = sum(_safe_file_size(file_path) for file_path in files)
    latest = max((_safe_mtime(file_path) for file_path in files), default=None)
    return {
        "path": str(path),
        "exists": path.exists(),
        "writable": _path_writable(path),
        "count": len(files),
        "size_bytes": size,
        "size_label": _bytes_label(size),
        "latest_label": _time_label(datetime.fromtimestamp(latest, UTC) if latest else None),
    }


def _voicemail_report(path: Path) -> dict[str, object]:
    report = _folder_report(path, pattern="default/*/*/msg*.wav")
    mailbox_root = path / "default"
    mailboxes = [item for item in mailbox_root.iterdir() if item.is_dir()] if mailbox_root.exists() else []
    report["messages"] = report["count"]
    report["mailboxes"] = len(mailboxes)
    return report


def _disk_report(path: Path) -> dict[str, object]:
    target = path if path.exists() else Path("/")
    usage = shutil.disk_usage(target)
    free_percent = round((usage.free / usage.total) * 100) if usage.total else 0
    used_percent = 100 - free_percent
    return {
        "total_label": _bytes_label(usage.total),
        "used_label": _bytes_label(usage.used),
        "free_label": _bytes_label(usage.free),
        "free_percent": free_percent,
        "used_percent": used_percent,
    }


def _safe_files(path: Path, pattern: str) -> list[Path]:
    if not path.exists():
        return []
    try:
        return [item for item in path.glob(pattern) if item.is_file()]
    except OSError:
        return []


def _safe_file_size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


def _safe_mtime(path: Path) -> float | None:
    try:
        return path.stat().st_mtime
    except OSError:
        return None


def _path_writable(path: Path) -> bool:
    if not path.exists():
        return False
    return path.is_dir() and os.access(path, os.W_OK)


def _recent_calls(connection: psycopg.Connection, where_sql: str, params: dict[str, object], *, limit: int) -> list[dict]:
    with connection.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            f"""
            SELECT
                TO_CHAR(calldate, 'YYYY-MM-DD HH24:MI:SS') AS call_time,
                COALESCE(NULLIF(src, ''), NULLIF(clid, ''), 'unknown') AS caller,
                COALESCE(NULLIF(dst, ''), NULLIF(callee_extension, ''), NULLIF(queue_name, ''), 'unknown') AS callee,
                COALESCE(direction, 'unknown') AS direction,
                disposition,
                billsec,
                CASE
                    WHEN {abandoned_call_condition()} THEN 'Abandoned'
                    WHEN {customer_missed_call_condition()} THEN 'Missed'
                    WHEN disposition = 'ANSWERED' THEN 'Answered'
                    ELSE COALESCE(disposition, 'Unknown')
                END AS simple_status
            FROM cdr_raw
            WHERE {where_sql}
            ORDER BY calldate DESC NULLS LAST, id DESC
            LIMIT %(limit)s
            """,
            {**params, "limit": limit},
        )
        rows = [dict(row) for row in cursor.fetchall()]
    for row in rows:
        row["talk_time_label"] = _duration_label(row["billsec"])
    return rows


def _daily_rows(connection: psycopg.Connection, where_sql: str, params: dict[str, object]) -> list[dict]:
    with connection.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            f"""
            SELECT
                TO_CHAR(calldate::date, 'YYYY-MM-DD') AS day,
                COUNT(*) AS total_calls,
                COALESCE(SUM(CASE WHEN COALESCE(direction, 'unknown') = 'inbound' THEN 1 ELSE 0 END), 0) AS inbound,
                COALESCE(SUM(CASE WHEN COALESCE(direction, 'unknown') = 'outbound' THEN 1 ELSE 0 END), 0) AS outbound,
                COALESCE(SUM(CASE WHEN disposition = 'ANSWERED' THEN 1 ELSE 0 END), 0) AS answered,
                COALESCE(SUM(CASE WHEN {customer_missed_call_condition()} THEN 1 ELSE 0 END), 0) AS missed,
                COALESCE(SUM(billsec), 0) AS talk_time
            FROM cdr_raw
            WHERE {where_sql}
              AND calldate IS NOT NULL
            GROUP BY calldate::date
            ORDER BY calldate::date DESC
            LIMIT 31
            """,
            params,
        )
        rows = [dict(row) for row in cursor.fetchall()]
    for row in rows:
        row["answer_rate"] = _percent(row["answered"], row["total_calls"])
        row["talk_time_label"] = _duration_label(row["talk_time"])
    return rows


def _disposition_rows(connection: psycopg.Connection, where_sql: str, params: dict[str, object]) -> list[dict]:
    with connection.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            f"""
            SELECT
                COALESCE(NULLIF(disposition, ''), 'UNKNOWN') AS disposition,
                COUNT(*) AS total_calls,
                COALESCE(SUM(billsec), 0) AS talk_time
            FROM cdr_raw
            WHERE {where_sql}
            GROUP BY COALESCE(NULLIF(disposition, ''), 'UNKNOWN')
            ORDER BY total_calls DESC, disposition
            LIMIT 12
            """,
            params,
        )
        rows = [dict(row) for row in cursor.fetchall()]
    total = sum(int(row.get("total_calls") or 0) for row in rows)
    for row in rows:
        row["share"] = _percent(row["total_calls"], total)
        row["talk_time_label"] = _duration_label(row["talk_time"])
    return rows


def _longest_calls(connection: psycopg.Connection, where_sql: str, params: dict[str, object]) -> list[dict]:
    with connection.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            f"""
            SELECT
                TO_CHAR(calldate, 'YYYY-MM-DD HH24:MI:SS') AS call_time,
                COALESCE(NULLIF(caller_extension, ''), NULLIF(src, ''), NULLIF(clid, ''), 'unknown') AS caller,
                COALESCE(NULLIF(callee_extension, ''), NULLIF(queue_name, ''), NULLIF(ivr_name, ''), NULLIF(dst, ''), 'unknown') AS callee,
                COALESCE(direction, 'unknown') AS direction,
                COALESCE(NULLIF(trunk_name, ''), NULLIF(route_name, ''), '-') AS path,
                billsec
            FROM cdr_raw
            WHERE {where_sql}
              AND disposition = 'ANSWERED'
            ORDER BY billsec DESC NULLS LAST, calldate DESC NULLS LAST
            LIMIT 10
            """,
            params,
        )
        rows = [dict(row) for row in cursor.fetchall()]
    for row in rows:
        row["talk_time_label"] = _duration_label(row["billsec"])
    return rows


def _hourly_rows(connection: psycopg.Connection, where_sql: str, params: dict[str, object]) -> list[dict]:
    with connection.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            f"""
            SELECT
                TO_CHAR(date_trunc('hour', calldate), 'HH24:00') AS hour_label,
                COUNT(*) AS total_calls,
                COALESCE(SUM(CASE WHEN disposition = 'ANSWERED' THEN 1 ELSE 0 END), 0) AS answered
            FROM cdr_raw
            WHERE {where_sql}
              AND calldate IS NOT NULL
            GROUP BY date_trunc('hour', calldate)
            ORDER BY date_trunc('hour', calldate) DESC
            LIMIT 12
            """,
            params,
        )
        return [dict(row) for row in cursor.fetchall()]


def _sections_with_counts(
    active: str,
    calls: dict[str, object],
    follow_up: dict[str, object],
    users: dict[str, object],
    queues: dict[str, object],
    trunks: dict[str, object],
    system: dict[str, object],
) -> list[dict[str, object]]:
    counts = {
        "overview": calls.get("total", 0),
        "kpi": f"{calls.get('answer_rate', 0)}%",
        "calls": calls.get("total", 0),
        "follow-up": follow_up.get("open_callbacks", 0),
        "users": users.get("enabled", 0),
        "queues": queues.get("enabled", 0),
        "trunks": trunks.get("enabled", 0),
        "system": system.get("status", "Check"),
    }
    return [{**item, "active": item["key"] == active, "count": counts.get(item["key"], "")} for item in REPORT_SECTIONS]


def _live_status_summary(total_extensions: int) -> dict[str, object]:
    snapshot = live_event_hub.get_snapshot() or {}
    users = snapshot.get("active_users") or []
    if users:
        online = len([user for user in users if user.get("status") in {"Online", "On Call"}])
        offline = len([user for user in users if user.get("status") == "Offline"])
        unknown = max(0, len(users) - online - offline)
        return {"online": online, "offline": offline, "unknown": unknown, "error": ""}

    summary = snapshot.get("summary") or {}
    if summary:
        return {
            "online": int(summary.get("active_users", 0) or 0),
            "offline": 0,
            "unknown": max(0, total_extensions - int(summary.get("active_users", 0) or 0)),
            "error": "",
        }
    return {"online": 0, "offline": 0, "unknown": total_extensions, "error": "Live snapshot is not ready yet."}


def _percent(value: object, total: object) -> int:
    value_int = int(value or 0)
    total_int = int(total or 0)
    if total_int <= 0:
        return 0
    return round((value_int / total_int) * 100)


def _duration_label(value: object) -> str:
    seconds = int(value or 0)
    if seconds <= 0:
        return "0s"
    minutes, remaining = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}h {minutes}m"
    if minutes:
        return f"{minutes}m {remaining}s"
    return f"{remaining}s"


def _time_label(value: object) -> str:
    if not value:
        return "No data"
    if isinstance(value, datetime):
        return value.astimezone(UTC).strftime("%Y-%m-%d %H:%M")
    return str(value)


def _bytes_label(value: object) -> str:
    size = float(value or 0)
    units = ["B", "KB", "MB", "GB", "TB"]
    unit = units[0]
    for unit in units:
        if size < 1024 or unit == units[-1]:
            break
        size = size / 1024
    if unit == "B":
        return f"{int(size)} {unit}"
    return f"{size:.1f} {unit}"


def _voicemail_count(spool_dir: Path) -> int:
    if not spool_dir.exists():
        return 0
    return len(list(spool_dir.glob("default/*/*/msg*.wav")))
