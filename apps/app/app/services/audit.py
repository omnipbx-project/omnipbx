from __future__ import annotations

from datetime import UTC, datetime

from psycopg.rows import dict_row
import psycopg
from psycopg.types.json import Json


def log_admin_event(
    connection: psycopg.Connection,
    *,
    event_type: str,
    actor_admin_id: int | None = None,
    actor_username: str | None = None,
    target_kind: str | None = None,
    target_value: str | None = None,
    message: str | None = None,
    details: dict | None = None,
) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO admin_audit_log (
                event_type, actor_admin_id, actor_username, target_kind, target_value, message, details_json
            )
            VALUES (%(event_type)s, %(actor_admin_id)s, %(actor_username)s, %(target_kind)s, %(target_value)s, %(message)s, %(details_json)s)
            """,
            {
                "event_type": event_type,
                "actor_admin_id": actor_admin_id,
                "actor_username": actor_username,
                "target_kind": target_kind,
                "target_value": target_value,
                "message": message,
                "details_json": Json(details or {}),
            },
        )


def list_admin_audit_entries(connection: psycopg.Connection, *, limit: int = 200) -> list[dict]:
    with connection.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT id, event_type, actor_admin_id, actor_username, target_kind, target_value, message, details_json, created_at
            FROM admin_audit_log
            ORDER BY created_at DESC, id DESC
            LIMIT %(limit)s
            """,
            {"limit": limit},
        )
        rows = cursor.fetchall()
    entries = []
    for row in rows:
        item = dict(row)
        created_at = item.get("created_at")
        if isinstance(created_at, datetime):
            item["created_at"] = created_at.astimezone(UTC)
        entries.append(item)
    return entries
