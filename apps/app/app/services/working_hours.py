import psycopg
from psycopg.rows import dict_row

from app.models.working_hours import WorkingHoursCreate
from app.services.audio import delete_custom_sound


LIST_WORKING_HOURS_SQL = """
SELECT id, name, start_day, end_day, start_time, end_time, inbound_route_name, after_hours_sound, enabled
FROM working_hours
ORDER BY name;
"""

UPSERT_WORKING_HOURS_SQL = """
INSERT INTO working_hours (
    name, start_day, end_day, start_time, end_time, inbound_route_name, after_hours_sound, enabled
)
VALUES (
    %(name)s, %(start_day)s, %(end_day)s, %(start_time)s, %(end_time)s, %(inbound_route_name)s, %(after_hours_sound)s, %(enabled)s
)
ON CONFLICT (name) DO UPDATE
SET start_day = EXCLUDED.start_day,
    end_day = EXCLUDED.end_day,
    start_time = EXCLUDED.start_time,
    end_time = EXCLUDED.end_time,
    inbound_route_name = EXCLUDED.inbound_route_name,
    after_hours_sound = EXCLUDED.after_hours_sound,
    enabled = EXCLUDED.enabled,
    updated_at = NOW()
RETURNING id, name, start_day, end_day, start_time, end_time, inbound_route_name, after_hours_sound, enabled;
"""

DELETE_WORKING_HOURS_SQL = """
DELETE FROM working_hours
WHERE name = %(name)s
RETURNING name, after_hours_sound;
"""


def list_working_hours(connection: psycopg.Connection) -> list[dict]:
    with connection.cursor(row_factory=dict_row) as cursor:
        cursor.execute(LIST_WORKING_HOURS_SQL)
        return list(cursor.fetchall())


def create_working_hours(connection: psycopg.Connection, payload: WorkingHoursCreate) -> dict:
    values = payload.model_dump()
    with connection.cursor(row_factory=dict_row) as cursor:
        cursor.execute("SELECT name FROM inbound_routes WHERE name = %(name)s", {"name": values["inbound_route_name"]})
        if not cursor.fetchone():
            raise ValueError("Selected inbound route does not exist.")
        cursor.execute(UPSERT_WORKING_HOURS_SQL, values)
        return cursor.fetchone()


def delete_working_hours(connection: psycopg.Connection, name: str) -> bool:
    with connection.cursor(row_factory=dict_row) as cursor:
        cursor.execute(DELETE_WORKING_HOURS_SQL, {"name": name})
        deleted = cursor.fetchone()
    if deleted:
        delete_custom_sound(deleted["after_hours_sound"])
    return bool(deleted)
