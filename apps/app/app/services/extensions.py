import secrets

import psycopg
from psycopg.rows import dict_row

from app.core.settings import get_settings
from app.models.extension import ExtensionCreate

DESK_PHONE_TRANSPORT = "transport-udp"
SOFTPHONE_TRANSPORT = "transport-udp-softphone"
WEBPHONE_TRANSPORT = "transport-wss"
PHONE_AUDIO_CODECS = "ulaw,alaw,g722"
PHONE_VIDEO_CODECS = ""
SOFTPHONE_AUDIO_CODECS = "opus,g722,ulaw,alaw"
SOFTPHONE_VIDEO_CODECS = "h264,vp8"
WEBPHONE_AUDIO_CODECS = "ulaw"
WEBPHONE_VIDEO_CODECS = ""
ADMIN_EXTENSION = "10000"

LIST_EXTENSIONS_SQL = """
SELECT id, extension, display_name, secret, context, transport, codecs, video_codecs, call_recording_enabled, enabled
FROM extensions
ORDER BY extension;
"""

DELETE_EXTENSION_SQL = """
DELETE FROM extensions
WHERE extension = %(extension)s
RETURNING extension;
"""

UPDATE_EXTENSION_SQL = """
UPDATE extensions
SET extension = %(new_extension)s,
    display_name = %(display_name)s,
    secret = COALESCE(%(secret)s, secret),
    transport = %(transport)s,
    codecs = %(codecs)s,
    video_codecs = %(video_codecs)s,
    call_recording_enabled = %(call_recording_enabled)s
WHERE extension = %(extension)s
RETURNING id, extension, display_name, secret, context, transport, codecs, video_codecs, call_recording_enabled, enabled;
"""

UPDATE_EXTENSION_SECRET_SQL = """
UPDATE extensions
SET secret = %(secret)s
WHERE extension = %(extension)s
RETURNING id, extension, display_name, secret, context, transport, codecs, video_codecs, call_recording_enabled, enabled;
"""

UPDATE_EXTENSION_ENABLED_SQL = """
UPDATE extensions
SET enabled = %(enabled)s
WHERE extension = %(extension)s
RETURNING id, extension, display_name, secret, context, transport, codecs, video_codecs, call_recording_enabled, enabled;
"""

INSERT_EXTENSION_SQL = """
INSERT INTO extensions (extension, display_name, secret, context, transport, codecs, video_codecs, call_recording_enabled, enabled)
VALUES (%(extension)s, %(display_name)s, %(secret)s, %(context)s, %(transport)s, %(codecs)s, %(video_codecs)s, %(call_recording_enabled)s, %(enabled)s)
RETURNING id, extension, display_name, secret, context, transport, codecs, video_codecs, call_recording_enabled, enabled;
"""


def list_extensions(connection: psycopg.Connection) -> list[dict]:
    with connection.cursor(row_factory=dict_row) as cursor:
        cursor.execute(LIST_EXTENSIONS_SQL)
        return list(cursor.fetchall())


def create_extension(connection: psycopg.Connection, payload: ExtensionCreate) -> dict:
    settings = get_settings()
    values = {
        "extension": payload.extension,
        "display_name": payload.display_name,
        "secret": payload.secret or secrets.token_hex(8),
        "context": settings.internal_context,
        "transport": payload.transport,
        "codecs": audio_codecs_for_transport(payload.transport),
        "video_codecs": video_codecs_for_transport(payload.transport),
        "call_recording_enabled": payload.call_recording_enabled,
        "enabled": payload.enabled,
    }
    with connection.cursor(row_factory=dict_row) as cursor:
        cursor.execute(INSERT_EXTENSION_SQL, values)
        return cursor.fetchone()


def delete_extension(connection: psycopg.Connection, extension: str) -> bool:
    if extension == ADMIN_EXTENSION:
        raise ValueError("Admin extension 10000 is permanent. You can change its phone type, but it cannot be deleted.")
    with connection.cursor(row_factory=dict_row) as cursor:
        cursor.execute(DELETE_EXTENSION_SQL, {"extension": extension})
        deleted = cursor.fetchone()
    return bool(deleted)


def update_extension_user(
    connection: psycopg.Connection,
    extension: str,
    new_extension: str,
    display_name: str,
    transport: str,
    call_recording_enabled: bool,
    secret: str | None = None,
) -> dict | None:
    if extension == ADMIN_EXTENSION and new_extension != ADMIN_EXTENSION:
        raise ValueError("Admin extension 10000 is permanent. You can change its phone type, but it cannot be renumbered.")
    with connection.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            UPDATE_EXTENSION_SQL,
            {
                "extension": extension,
                "new_extension": new_extension,
                "display_name": display_name,
                "transport": transport,
                "codecs": audio_codecs_for_transport(transport),
                "video_codecs": video_codecs_for_transport(transport),
                "call_recording_enabled": call_recording_enabled,
                "secret": secret,
            },
        )
        return cursor.fetchone()


def update_extension_secret(connection: psycopg.Connection, extension: str, secret: str) -> dict | None:
    with connection.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            UPDATE_EXTENSION_SECRET_SQL,
            {"extension": extension, "secret": secret},
        )
        return cursor.fetchone()


def update_extension_enabled(connection: psycopg.Connection, extension: str, enabled: bool) -> dict | None:
    with connection.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            UPDATE_EXTENSION_ENABLED_SQL,
            {"extension": extension, "enabled": enabled},
        )
        return cursor.fetchone()


def audio_codecs_for_transport(transport: str) -> str:
    if transport == WEBPHONE_TRANSPORT:
        return WEBPHONE_AUDIO_CODECS
    if transport == SOFTPHONE_TRANSPORT:
        return SOFTPHONE_AUDIO_CODECS
    return PHONE_AUDIO_CODECS


def video_codecs_for_transport(transport: str) -> str:
    if transport == WEBPHONE_TRANSPORT:
        return WEBPHONE_VIDEO_CODECS
    if transport == SOFTPHONE_TRANSPORT:
        return SOFTPHONE_VIDEO_CODECS
    return PHONE_VIDEO_CODECS


def pjsip_transport_for_device(transport: str) -> str:
    if transport == WEBPHONE_TRANSPORT:
        return "transport-wss"
    return "transport-udp"
