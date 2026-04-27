import psycopg
from psycopg.rows import dict_row

from app.models.trunk import TrunkCreate


LIST_TRUNKS_SQL = """
SELECT id, name, provider_name, host, username, password, transport, register_enabled,
       match_ip, codecs, outbound_prefix, strip_digits, enabled
FROM trunks
ORDER BY name;
"""

INSERT_TRUNK_SQL = """
INSERT INTO trunks (
    name, provider_name, host, username, password, transport, register_enabled,
    match_ip, codecs, outbound_prefix, strip_digits, enabled
)
VALUES (
    %(name)s, %(provider_name)s, %(host)s, %(username)s, %(password)s, %(transport)s, %(register_enabled)s,
    %(match_ip)s, %(codecs)s, %(outbound_prefix)s, %(strip_digits)s, %(enabled)s
)
RETURNING id, name, provider_name, host, username, password, transport, register_enabled,
          match_ip, codecs, outbound_prefix, strip_digits, enabled;
"""

DELETE_TRUNK_SQL = """
DELETE FROM trunks
WHERE name = %(name)s
RETURNING name;
"""

DELETE_TRUNK_ROUTES_SQL = """
DELETE FROM inbound_routes
WHERE trunk_name = %(name)s;
"""

DELETE_TRUNK_WORKING_HOURS_SQL = """
DELETE FROM working_hours
WHERE inbound_route_name IN (
    SELECT name FROM inbound_routes WHERE trunk_name = %(name)s
);
"""

DELETE_TRUNK_WELCOME_SQL = """
DELETE FROM welcome_messages
WHERE inbound_route_name IN (
    SELECT name FROM inbound_routes WHERE trunk_name = %(name)s
);
"""


def list_trunks(connection: psycopg.Connection) -> list[dict]:
    with connection.cursor(row_factory=dict_row) as cursor:
        cursor.execute(LIST_TRUNKS_SQL)
        return list(cursor.fetchall())


def create_trunk(connection: psycopg.Connection, payload: TrunkCreate) -> dict:
    values = payload.model_dump()
    with connection.cursor(row_factory=dict_row) as cursor:
        cursor.execute(INSERT_TRUNK_SQL, values)
        return cursor.fetchone()


def delete_trunk(connection: psycopg.Connection, name: str) -> bool:
    with connection.cursor(row_factory=dict_row) as cursor:
        cursor.execute(DELETE_TRUNK_WORKING_HOURS_SQL, {"name": name})
        cursor.execute(DELETE_TRUNK_WELCOME_SQL, {"name": name})
        cursor.execute(DELETE_TRUNK_ROUTES_SQL, {"name": name})
        cursor.execute(DELETE_TRUNK_SQL, {"name": name})
        deleted = cursor.fetchone()
    return bool(deleted)
