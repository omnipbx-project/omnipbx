import psycopg
from psycopg.rows import dict_row

from app.models.ivr import IvrCreate
from app.services.audio import delete_custom_sound


LIST_IVRS_SQL = """
SELECT id, name, extension, prompt, timeout, invalid_retries, enabled
FROM ivr_menus
ORDER BY extension;
"""

LIST_IVR_OPTIONS_SQL = """
SELECT digit, destination_type, destination_value
FROM ivr_options
WHERE ivr_id = %(ivr_id)s
ORDER BY digit;
"""

UPSERT_IVR_SQL = """
INSERT INTO ivr_menus (name, extension, prompt, timeout, invalid_retries, enabled)
VALUES (%(name)s, %(extension)s, %(prompt)s, %(timeout)s, %(invalid_retries)s, %(enabled)s)
ON CONFLICT (name) DO UPDATE
SET extension = EXCLUDED.extension,
    prompt = EXCLUDED.prompt,
    timeout = EXCLUDED.timeout,
    invalid_retries = EXCLUDED.invalid_retries,
    enabled = EXCLUDED.enabled,
    updated_at = NOW()
RETURNING id, name, extension, prompt, timeout, invalid_retries, enabled;
"""

GET_IVR_ID_SQL = """
SELECT id
FROM ivr_menus
WHERE name = %(name)s;
"""

DELETE_IVR_OPTIONS_SQL = """
DELETE FROM ivr_options
WHERE ivr_id = %(ivr_id)s;
"""

INSERT_IVR_OPTION_SQL = """
INSERT INTO ivr_options (ivr_id, digit, destination_type, destination_value)
VALUES (%(ivr_id)s, %(digit)s, %(destination_type)s, %(destination_value)s);
"""

IVR_USAGE_SQL = """
SELECT EXISTS (
    SELECT 1 FROM inbound_routes
    WHERE destination_type = 'ivr' AND destination_value = %(extension)s
) OR EXISTS (
    SELECT 1 FROM ivr_options
    WHERE destination_type = 'ivr' AND destination_value = %(extension)s
) AS in_use;
"""

DELETE_IVR_SQL = """
DELETE FROM ivr_menus
WHERE name = %(name)s
RETURNING name, prompt;
"""


def list_ivrs(connection: psycopg.Connection) -> list[dict]:
    with connection.cursor(row_factory=dict_row) as cursor:
        cursor.execute(LIST_IVRS_SQL)
        ivrs = list(cursor.fetchall())
        for ivr in ivrs:
            cursor.execute(LIST_IVR_OPTIONS_SQL, {"ivr_id": ivr["id"]})
            ivr["options"] = list(cursor.fetchall())
    return ivrs


def create_ivr(connection: psycopg.Connection, payload: IvrCreate) -> dict:
    values = payload.model_dump()
    with connection.cursor(row_factory=dict_row) as cursor:
        cursor.execute(UPSERT_IVR_SQL, values)
        record = cursor.fetchone()
        cursor.execute(GET_IVR_ID_SQL, {"name": values["name"]})
        ivr_id = cursor.fetchone()["id"]
        cursor.execute(DELETE_IVR_OPTIONS_SQL, {"ivr_id": ivr_id})
        for option in values["options"]:
            cursor.execute(INSERT_IVR_OPTION_SQL, {"ivr_id": ivr_id, **option})
        record["options"] = values["options"]
    return record


def delete_ivr(connection: psycopg.Connection, name: str) -> bool:
    with connection.cursor(row_factory=dict_row) as cursor:
        cursor.execute("SELECT id, extension FROM ivr_menus WHERE name = %(name)s", {"name": name})
        row = cursor.fetchone()
        if not row:
            return False
        cursor.execute(IVR_USAGE_SQL, {"extension": row["extension"]})
        if cursor.fetchone()["in_use"]:
            raise ValueError("IVR is still used by an inbound route or another IVR option.")
        cursor.execute(DELETE_IVR_OPTIONS_SQL, {"ivr_id": row["id"]})
        cursor.execute(DELETE_IVR_SQL, {"name": name})
        deleted = cursor.fetchone()
    if deleted:
        delete_custom_sound(deleted["prompt"])
    return bool(deleted)
