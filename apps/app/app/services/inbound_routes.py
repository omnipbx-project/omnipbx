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

UPDATE_INBOUND_ROUTE_SQL = """
UPDATE inbound_routes
SET name = %(name)s,
    trunk_name = %(trunk_name)s,
    did_pattern = %(did_pattern)s,
    destination_type = %(destination_type)s,
    destination_value = %(destination_value)s,
    enabled = %(enabled)s
WHERE name = %(old_name)s
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

UPDATE_WORKING_HOURS_ROUTE_NAME_SQL = """
UPDATE working_hours
SET inbound_route_name = %(new_name)s,
    updated_at = NOW()
WHERE inbound_route_name = %(old_name)s;
"""

UPDATE_WELCOME_ROUTE_NAME_SQL = """
UPDATE welcome_messages
SET inbound_route_name = %(new_name)s,
    updated_at = NOW()
WHERE inbound_route_name = %(old_name)s;
"""


def list_inbound_routes(connection: psycopg.Connection) -> list[dict]:
    with connection.cursor(row_factory=dict_row) as cursor:
        cursor.execute(LIST_INBOUND_ROUTES_SQL)
        return list(cursor.fetchall())


def create_inbound_route(connection: psycopg.Connection, payload: InboundRouteCreate) -> dict:
    values = payload.model_dump()
    with connection.cursor(row_factory=dict_row) as cursor:
        _validate_route_references(cursor, values)
        cursor.execute(INSERT_INBOUND_ROUTE_SQL, values)
        return cursor.fetchone()


def update_inbound_route(connection: psycopg.Connection, old_name: str, payload: InboundRouteCreate) -> dict | None:
    values = payload.model_dump()
    values["old_name"] = old_name
    with connection.cursor(row_factory=dict_row) as cursor:
        _validate_route_references(cursor, values)
        cursor.execute(UPDATE_INBOUND_ROUTE_SQL, values)
        record = cursor.fetchone()
        if record:
            route_names = {"old_name": old_name, "new_name": values["name"]}
            cursor.execute(UPDATE_WORKING_HOURS_ROUTE_NAME_SQL, route_names)
            cursor.execute(UPDATE_WELCOME_ROUTE_NAME_SQL, route_names)
        return record


def delete_inbound_route(connection: psycopg.Connection, name: str) -> bool:
    with connection.cursor(row_factory=dict_row) as cursor:
        cursor.execute(DELETE_INBOUND_ROUTE_WORKING_HOURS_SQL, {"name": name})
        cursor.execute(DELETE_INBOUND_ROUTE_WELCOME_SQL, {"name": name})
        cursor.execute(DELETE_INBOUND_ROUTE_SQL, {"name": name})
        deleted = cursor.fetchone()
    return bool(deleted)


def _validate_route_references(cursor: psycopg.Cursor, values: dict) -> None:
    cursor.execute("SELECT 1 FROM trunks WHERE name = %(name)s", {"name": values["trunk_name"]})
    if not cursor.fetchone():
        raise ValueError("Selected trunk does not exist.")

    destination_type = values["destination_type"]
    destination_values = _split_csv(values["destination_value"])
    if not destination_values:
        raise ValueError("Choose at least one destination.")
    for destination_value in destination_values:
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
            raise ValueError(f"Selected destination {destination_value} does not exist.")


def _split_csv(value: str) -> list[str]:
    return [item.strip() for item in str(value or "").split(",") if item.strip()]
