import psycopg
from psycopg.rows import dict_row

from app.models.welcome_message import WelcomeMessageCreate
from app.services.audio import delete_custom_sound


LIST_WELCOME_MESSAGES_SQL = """
SELECT id, name, sound_name, inbound_route_name, enabled
FROM welcome_messages
ORDER BY name;
"""

UPSERT_WELCOME_MESSAGE_SQL = """
INSERT INTO welcome_messages (name, sound_name, inbound_route_name, enabled)
VALUES (%(name)s, %(sound_name)s, %(inbound_route_name)s, %(enabled)s)
ON CONFLICT (name) DO UPDATE
SET sound_name = EXCLUDED.sound_name,
    inbound_route_name = EXCLUDED.inbound_route_name,
    enabled = EXCLUDED.enabled,
    updated_at = NOW()
RETURNING id, name, sound_name, inbound_route_name, enabled;
"""

DELETE_WELCOME_MESSAGE_SQL = """
DELETE FROM welcome_messages
WHERE name = %(name)s
RETURNING name, sound_name;
"""


def list_welcome_messages(connection: psycopg.Connection) -> list[dict]:
    with connection.cursor(row_factory=dict_row) as cursor:
        cursor.execute(LIST_WELCOME_MESSAGES_SQL)
        return list(cursor.fetchall())


def create_welcome_message(connection: psycopg.Connection, payload: WelcomeMessageCreate) -> dict:
    values = payload.model_dump()
    with connection.cursor(row_factory=dict_row) as cursor:
        cursor.execute("SELECT name FROM inbound_routes WHERE name = %(name)s", {"name": values["inbound_route_name"]})
        if not cursor.fetchone():
            raise ValueError("Selected inbound route does not exist.")
        cursor.execute(UPSERT_WELCOME_MESSAGE_SQL, values)
        return cursor.fetchone()


def delete_welcome_message(connection: psycopg.Connection, name: str) -> bool:
    with connection.cursor(row_factory=dict_row) as cursor:
        cursor.execute(DELETE_WELCOME_MESSAGE_SQL, {"name": name})
        deleted = cursor.fetchone()
    if deleted:
        delete_custom_sound(deleted["sound_name"])
    return bool(deleted)
