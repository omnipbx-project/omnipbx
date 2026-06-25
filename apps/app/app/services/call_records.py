from __future__ import annotations

import psycopg
from psycopg.rows import dict_row

from app.services.call_logs import resolve_recording_path, sync_cdr_from_asterisk
from app.services.date_ranges import parse_date_bound
from app.services.extensions import list_extensions


def list_call_records(
    connection: psycopg.Connection,
    *,
    search: str = "",
    direction: str = "all",
    user: str = "all",
    date_from: str | None = None,
    date_to: str | None = None,
    timezone_name: str = "UTC",
    limit: int = 200,
) -> dict[str, object]:
    sync_cdr_from_asterisk(connection)
    where = ["COALESCE(NULLIF(recordingfile, ''), '') <> ''"]
    params: dict[str, object] = {"limit": limit}
    search = search.strip()
    if search:
        params["search"] = f"%{search}%"
        where.append(
            """
            (
                COALESCE(src, '') ILIKE %(search)s OR
                COALESCE(dst, '') ILIKE %(search)s OR
                COALESCE(caller_extension, '') ILIKE %(search)s OR
                COALESCE(callee_extension, '') ILIKE %(search)s OR
                COALESCE(recordingfile, '') ILIKE %(search)s
            )
            """
        )
    if direction != "all":
        params["direction"] = direction
        where.append("COALESCE(direction, 'unknown') = %(direction)s")
    if user != "all":
        params["user"] = user
        where.append(
            """
            (
                COALESCE(NULLIF(caller_extension, ''), '') = %(user)s OR
                COALESCE(NULLIF(callee_extension, ''), '') = %(user)s OR
                COALESCE(NULLIF(src, ''), '') = %(user)s OR
                COALESCE(NULLIF(dst, ''), '') = %(user)s
            )
            """
        )
    if date_from:
        params["date_from"] = _date_bound(date_from, end_of_day=False, timezone_name=timezone_name)
        where.append("calldate >= %(date_from)s::timestamptz")
    if date_to:
        params["date_to"] = _date_bound(date_to, end_of_day=True, timezone_name=timezone_name)
        where.append("calldate <= %(date_to)s::timestamptz")

    where_sql = " AND ".join(where)
    with connection.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            f"""
            SELECT
                COUNT(*) AS total,
                COALESCE(SUM(CASE WHEN COALESCE(direction, 'unknown') = 'inbound' THEN 1 ELSE 0 END), 0) AS inbound,
                COALESCE(SUM(CASE WHEN COALESCE(direction, 'unknown') = 'outbound' THEN 1 ELSE 0 END), 0) AS outbound,
                COALESCE(SUM(CASE WHEN COALESCE(direction, 'unknown') = 'internal' THEN 1 ELSE 0 END), 0) AS internal,
                COALESCE(SUM(billsec), 0) AS talk_time
            FROM cdr_raw
            WHERE {where_sql}
            """,
            {key: value for key, value in params.items() if key != "limit"},
        )
        summary = dict(cursor.fetchone())
        cursor.execute(
            f"""
            SELECT
                id,
                TO_CHAR(calldate, 'YYYY-MM-DD HH24:MI:SS') AS call_time,
                COALESCE(NULLIF(src, ''), NULLIF(clid, ''), 'unknown') AS caller,
                COALESCE(NULLIF(dst, ''), NULLIF(callee_extension, ''), 'unknown') AS callee,
                COALESCE(direction, 'unknown') AS direction,
                COALESCE(NULLIF(caller_extension, ''), '-') AS caller_extension,
                COALESCE(NULLIF(callee_extension, ''), '-') AS callee_extension,
                disposition,
                billsec,
                recordingfile
            FROM cdr_raw
            WHERE {where_sql}
            ORDER BY calldate DESC NULLS LAST, id DESC
            LIMIT %(limit)s
            """,
            params,
        )
        rows = [dict(row) for row in cursor.fetchall()]

    return {
        "rows": [_with_recording(row) for row in rows],
        "summary": {
            **summary,
            "talk_time_label": _duration_label(summary.get("talk_time")),
        },
        "users": list_extensions(connection),
    }


def _with_recording(row: dict) -> dict:
    path = resolve_recording_path(row.get("recordingfile"))
    row["recording_available"] = bool(path)
    row["recording_name"] = path.name if path else row.get("recordingfile")
    row["recording_url"] = f"/api/call-recordings/{path.name}" if path else ""
    row["talk_time_label"] = _duration_label(row.get("billsec"))
    return row


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


def _date_bound(value: str, *, end_of_day: bool, timezone_name: str = "UTC"):
    return parse_date_bound(value, end_of_day=end_of_day, timezone_name=timezone_name)
