from __future__ import annotations

import psycopg
from psycopg.rows import dict_row

from app.models.softphone import SoftphoneSettingsPayload


def get_softphone_settings(connection: psycopg.Connection) -> dict:
    with connection.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT enabled, websocket_url, sip_domain, display_name_prefix, public_host, note
            FROM softphone_settings
            WHERE id = 1
            """
        )
        return dict(cursor.fetchone())


def save_softphone_settings(connection: psycopg.Connection, payload: SoftphoneSettingsPayload) -> dict:
    values = payload.model_dump()
    with connection.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            UPDATE softphone_settings
            SET
                enabled = %(enabled)s,
                websocket_url = %(websocket_url)s,
                sip_domain = %(sip_domain)s,
                display_name_prefix = %(display_name_prefix)s,
                public_host = %(public_host)s,
                note = %(note)s,
                updated_at = NOW()
            WHERE id = 1
            """
            ,
            values,
        )
    return get_softphone_settings(connection)


def set_softphone_dnd(connection: psycopg.Connection, extension: str, enabled: bool) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO softphone_extension_state (extension, dnd_enabled, updated_at)
            VALUES (%(extension)s, %(enabled)s, NOW())
            ON CONFLICT (extension) DO UPDATE
            SET dnd_enabled = EXCLUDED.dnd_enabled, updated_at = NOW()
            """,
            {"extension": extension, "enabled": enabled},
        )


def get_softphone_dnd(connection: psycopg.Connection, extension: str) -> bool:
    with connection.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            "SELECT dnd_enabled FROM softphone_extension_state WHERE extension = %(extension)s",
            {"extension": extension},
        )
        row = cursor.fetchone()
    return bool(row["dnd_enabled"]) if row else False


def build_softphone_bootstrap(connection: psycopg.Connection, extension: str) -> dict:
    settings = get_softphone_settings(connection)
    with connection.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT extension, display_name, secret, context, enabled
            FROM extensions
            WHERE extension = %(extension)s
            """,
            {"extension": extension},
        )
        row = cursor.fetchone()
    if not row:
        raise ValueError(f"Extension {extension} was not found.")
    return {
        "enabled": bool(settings["enabled"]),
        "webrtc_ready": bool(settings["enabled"] and settings.get("websocket_url") and settings.get("sip_domain")),
        "extension": row["extension"],
        "display_name": row["display_name"],
        "secret": row["secret"],
        "context": row["context"],
        "sip_domain": settings.get("sip_domain"),
        "websocket_url": settings.get("websocket_url"),
        "public_host": settings.get("public_host"),
        "display_name_prefix": settings.get("display_name_prefix"),
        "note": settings.get("note"),
        "dnd_enabled": get_softphone_dnd(connection, row["extension"]),
    }
