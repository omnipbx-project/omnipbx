import psycopg
from psycopg.rows import dict_row

from app.models.trunk import TrunkCreate


LIST_TRUNKS_SQL = """
SELECT id, name, provider_name, main_number, host, username, password, transport, register_enabled,
       match_ip, codecs, outbound_prefix, strip_digits, enabled
FROM trunks
ORDER BY name;
"""

INSERT_TRUNK_SQL = """
INSERT INTO trunks (
    name, provider_name, main_number, host, username, password, transport, register_enabled,
    match_ip, codecs, outbound_prefix, strip_digits, enabled
)
VALUES (
    %(name)s, %(provider_name)s, %(main_number)s, %(host)s, %(username)s, %(password)s, %(transport)s, %(register_enabled)s,
    %(match_ip)s, %(codecs)s, %(outbound_prefix)s, %(strip_digits)s, %(enabled)s
)
RETURNING id, name, provider_name, main_number, host, username, password, transport, register_enabled,
          match_ip, codecs, outbound_prefix, strip_digits, enabled;
"""

DELETE_TRUNK_SQL = """
DELETE FROM trunks
WHERE name = %(name)s
RETURNING name;
"""

UPDATE_TRUNK_SQL = """
UPDATE trunks
SET name = %(new_name)s,
    provider_name = %(provider_name)s,
    main_number = %(main_number)s,
    host = %(host)s,
    username = %(username)s,
    password = %(password)s,
    transport = %(transport)s,
    register_enabled = %(register_enabled)s,
    match_ip = %(match_ip)s,
    codecs = %(codecs)s,
    outbound_prefix = %(outbound_prefix)s,
    strip_digits = %(strip_digits)s,
    enabled = %(enabled)s,
    updated_at = NOW()
WHERE name = %(name)s
RETURNING id, name, provider_name, main_number, host, username, password, transport, register_enabled,
          match_ip, codecs, outbound_prefix, strip_digits, enabled;
"""

UPDATE_TRUNK_ENABLED_SQL = """
UPDATE trunks
SET enabled = %(enabled)s,
    updated_at = NOW()
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


def update_trunk(connection: psycopg.Connection, name: str, payload: TrunkCreate) -> dict | None:
    values = payload.model_dump()
    values["name"] = name
    values["new_name"] = payload.name
    with connection.cursor(row_factory=dict_row) as cursor:
        cursor.execute(UPDATE_TRUNK_SQL, values)
        return cursor.fetchone()


def update_trunk_enabled(connection: psycopg.Connection, name: str, enabled: bool) -> bool:
    with connection.cursor(row_factory=dict_row) as cursor:
        cursor.execute(UPDATE_TRUNK_ENABLED_SQL, {"name": name, "enabled": enabled})
        return bool(cursor.fetchone())
