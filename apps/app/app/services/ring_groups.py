import psycopg
from psycopg.rows import dict_row

from app.models.ring_group import RingGroupCreate


LIST_RING_GROUPS_SQL = """
SELECT id, name, extension, ring_strategy, ring_timeout, enabled
FROM ring_groups
ORDER BY extension;
"""

LIST_RING_GROUP_MEMBERS_SQL = """
SELECT extension
FROM ring_group_members
WHERE ring_group_id = %(ring_group_id)s
ORDER BY position, extension;
"""

INSERT_RING_GROUP_SQL = """
INSERT INTO ring_groups (name, extension, ring_strategy, ring_timeout, enabled)
VALUES (%(name)s, %(extension)s, %(ring_strategy)s, %(ring_timeout)s, %(enabled)s)
ON CONFLICT (name) DO UPDATE
SET extension = EXCLUDED.extension,
    ring_strategy = EXCLUDED.ring_strategy,
    ring_timeout = EXCLUDED.ring_timeout,
    enabled = EXCLUDED.enabled,
    updated_at = NOW()
RETURNING id, name, extension, ring_strategy, ring_timeout, enabled;
"""

GET_RING_GROUP_ID_SQL = """
SELECT id
FROM ring_groups
WHERE name = %(name)s;
"""

DELETE_RING_GROUP_MEMBERS_SQL = """
DELETE FROM ring_group_members
WHERE ring_group_id = %(ring_group_id)s;
"""

INSERT_RING_GROUP_MEMBER_SQL = """
INSERT INTO ring_group_members (ring_group_id, extension, position)
VALUES (%(ring_group_id)s, %(extension)s, %(position)s);
"""

DELETE_RING_GROUP_SQL = """
DELETE FROM ring_groups
WHERE name = %(name)s
RETURNING name, extension;
"""

RING_GROUP_USAGE_SQL = """
SELECT EXISTS (
    SELECT 1 FROM inbound_routes
    WHERE destination_type = 'ring_group' AND destination_value = %(extension)s
) OR EXISTS (
    SELECT 1 FROM ivr_options
    WHERE destination_type = 'ring_group' AND destination_value = %(extension)s
) AS in_use;
"""


def list_ring_groups(connection: psycopg.Connection) -> list[dict]:
    with connection.cursor(row_factory=dict_row) as cursor:
        cursor.execute(LIST_RING_GROUPS_SQL)
        groups = list(cursor.fetchall())
        for group in groups:
            cursor.execute(LIST_RING_GROUP_MEMBERS_SQL, {"ring_group_id": group["id"]})
            group["members"] = [row["extension"] for row in cursor.fetchall()]
    return groups


def create_ring_group(connection: psycopg.Connection, payload: RingGroupCreate) -> dict:
    values = payload.model_dump()
    with connection.cursor(row_factory=dict_row) as cursor:
        cursor.execute(INSERT_RING_GROUP_SQL, values)
        record = cursor.fetchone()
        cursor.execute(GET_RING_GROUP_ID_SQL, {"name": values["name"]})
        ring_group_id = cursor.fetchone()["id"]
        cursor.execute(DELETE_RING_GROUP_MEMBERS_SQL, {"ring_group_id": ring_group_id})
        for position, member in enumerate(values["members"], start=1):
            cursor.execute(
                INSERT_RING_GROUP_MEMBER_SQL,
                {"ring_group_id": ring_group_id, "extension": member, "position": position},
            )
        record["members"] = values["members"]
    return record


def delete_ring_group(connection: psycopg.Connection, name: str) -> bool:
    with connection.cursor(row_factory=dict_row) as cursor:
        cursor.execute("SELECT extension, id FROM ring_groups WHERE name = %(name)s", {"name": name})
        row = cursor.fetchone()
        if not row:
            return False
        cursor.execute(RING_GROUP_USAGE_SQL, {"extension": row["extension"]})
        if cursor.fetchone()["in_use"]:
            raise ValueError("Ring group is still used by an inbound route or IVR option.")
        cursor.execute(DELETE_RING_GROUP_MEMBERS_SQL, {"ring_group_id": row["id"]})
        cursor.execute(DELETE_RING_GROUP_SQL, {"name": name})
        return bool(cursor.fetchone())
