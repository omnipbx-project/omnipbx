import secrets

import psycopg
from psycopg.rows import dict_row

from app.core.settings import get_settings
from app.models.extension import ExtensionCreate


LIST_EXTENSIONS_SQL = """
SELECT id, extension, display_name, secret, context, enabled
FROM extensions
ORDER BY extension;
"""

DELETE_EXTENSION_SQL = """
DELETE FROM extensions
WHERE extension = %(extension)s
RETURNING extension;
"""

INSERT_EXTENSION_SQL = """
INSERT INTO extensions (extension, display_name, secret, context, enabled)
VALUES (%(extension)s, %(display_name)s, %(secret)s, %(context)s, %(enabled)s)
RETURNING id, extension, display_name, secret, context, enabled;
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
        "enabled": payload.enabled,
    }
    with connection.cursor(row_factory=dict_row) as cursor:
        cursor.execute(INSERT_EXTENSION_SQL, values)
        return cursor.fetchone()


def delete_extension(connection: psycopg.Connection, extension: str) -> bool:
    with connection.cursor(row_factory=dict_row) as cursor:
        cursor.execute(DELETE_EXTENSION_SQL, {"extension": extension})
        deleted = cursor.fetchone()
    return bool(deleted)
