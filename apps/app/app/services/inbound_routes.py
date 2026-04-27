import psycopg
from psycopg.rows import dict_row

from app.models.inbound_route import InboundRouteCreate


LIST_INBOUND_ROUTES_SQL = """
SELECT id, name, trunk_name, did_pattern, destination_type, destination_value, enabled
FROM inbound_routes
ORDER BY name;
"""

INSERT_INBOUND_ROUTE_SQL = """
INSERT INTO inbound_routes (
    name, trunk_name, did_pattern, destination_type, destination_value, enabled
)
VALUES (
    %(name)s, %(trunk_name)s, %(did_pattern)s, %(destination_type)s, %(destination_value)s, %(enabled)s
)
RETURNING id, name, trunk_name, did_pattern, destination_type, destination_value, enabled;
"""

DELETE_INBOUND_ROUTE_SQL = """
DELETE FROM inbound_routes
WHERE name = %(name)s
RETURNING name;
"""

DELETE_INBOUND_ROUTE_WORKING_HOURS_SQL = """
DELETE FROM working_hours
WHERE inbound_route_name = %(name)s;
"""

DELETE_INBOUND_ROUTE_WELCOME_SQL = """
DELETE FROM welcome_messages
WHERE inbound_route_name = %(name)s;
"""


def list_inbound_routes(connection: psycopg.Connection) -> list[dict]:
    with connection.cursor(row_factory=dict_row) as cursor:
        cursor.execute(LIST_INBOUND_ROUTES_SQL)
        return list(cursor.fetchall())


def create_inbound_route(connection: psycopg.Connection, payload: InboundRouteCreate) -> dict:
    values = payload.model_dump()
    with connection.cursor(row_factory=dict_row) as cursor:
        cursor.execute("SELECT 1 FROM trunks WHERE name = %(name)s", {"name": values["trunk_name"]})
        if not cursor.fetchone():
            raise ValueError("Selected trunk does not exist.")
        destination_type = values["destination_type"]
        destination_value = values["destination_value"]
        if destination_type == "extension":
            cursor.execute("SELECT 1 FROM extensions WHERE extension = %(value)s", {"value": destination_value})
        elif destination_type == "trunk":
            cursor.execute("SELECT 1 FROM trunks WHERE name = %(value)s", {"value": destination_value})
        elif destination_type == "queue":
            cursor.execute("SELECT 1 FROM queues_custom WHERE extension = %(value)s", {"value": destination_value})
        elif destination_type == "ivr":
            cursor.execute("SELECT 1 FROM ivr_menus WHERE extension = %(value)s", {"value": destination_value})
        elif destination_type == "ring_group":
            cursor.execute("SELECT 1 FROM ring_groups WHERE extension = %(value)s", {"value": destination_value})
        if not cursor.fetchone():
            raise ValueError("Selected destination does not exist.")
        cursor.execute(INSERT_INBOUND_ROUTE_SQL, values)
        return cursor.fetchone()


def delete_inbound_route(connection: psycopg.Connection, name: str) -> bool:
    with connection.cursor(row_factory=dict_row) as cursor:
        cursor.execute(DELETE_INBOUND_ROUTE_WORKING_HOURS_SQL, {"name": name})
        cursor.execute(DELETE_INBOUND_ROUTE_WELCOME_SQL, {"name": name})
        cursor.execute(DELETE_INBOUND_ROUTE_SQL, {"name": name})
        deleted = cursor.fetchone()
    return bool(deleted)
