import psycopg
from psycopg.rows import dict_row

from app.models.queue import QueueCreate
from app.services.audio import delete_queue_moh


LIST_QUEUES_SQL = """
SELECT id, name, extension, strategy, timeout, retry, wrapuptime, max_wait_time,
       announce_position, musicclass, moh_file_name, enabled, voicemail_enabled, voicemail_mailbox
FROM queues_custom
ORDER BY extension;
"""

LIST_QUEUE_MEMBERS_SQL = """
SELECT extension
FROM queue_members_custom
WHERE queue_id = %(queue_id)s
ORDER BY member_order, extension;
"""

UPSERT_QUEUE_SQL = """
INSERT INTO queues_custom (
    name, extension, strategy, timeout, retry, wrapuptime, max_wait_time,
    announce_position, musicclass, moh_file_name, enabled, voicemail_enabled, voicemail_mailbox
)
VALUES (
    %(name)s, %(extension)s, %(strategy)s, %(timeout)s, %(retry)s, %(wrapuptime)s, %(max_wait_time)s,
    %(announce_position)s, %(musicclass)s, %(moh_file_name)s, %(enabled)s, %(voicemail_enabled)s, %(voicemail_mailbox)s
)
ON CONFLICT (name) DO UPDATE
SET extension = EXCLUDED.extension,
    strategy = EXCLUDED.strategy,
    timeout = EXCLUDED.timeout,
    retry = EXCLUDED.retry,
    wrapuptime = EXCLUDED.wrapuptime,
    max_wait_time = EXCLUDED.max_wait_time,
    announce_position = EXCLUDED.announce_position,
    musicclass = EXCLUDED.musicclass,
    moh_file_name = EXCLUDED.moh_file_name,
    enabled = EXCLUDED.enabled,
    voicemail_enabled = EXCLUDED.voicemail_enabled,
    voicemail_mailbox = EXCLUDED.voicemail_mailbox,
    updated_at = NOW()
RETURNING id, name, extension, strategy, timeout, retry, wrapuptime, max_wait_time,
          announce_position, musicclass, moh_file_name, enabled, voicemail_enabled, voicemail_mailbox;
"""

GET_QUEUE_ID_SQL = """
SELECT id
FROM queues_custom
WHERE name = %(name)s;
"""

DELETE_QUEUE_MEMBERS_SQL = """
DELETE FROM queue_members_custom
WHERE queue_id = %(queue_id)s;
"""

INSERT_QUEUE_MEMBER_SQL = """
INSERT INTO queue_members_custom (queue_id, extension, member_order)
VALUES (%(queue_id)s, %(extension)s, %(member_order)s);
"""

QUEUE_USAGE_SQL = """
SELECT EXISTS (
    SELECT 1 FROM inbound_routes
    WHERE destination_type = 'queue' AND destination_value = %(extension)s
) OR EXISTS (
    SELECT 1 FROM ivr_options
    WHERE destination_type = 'queue' AND destination_value = %(extension)s
) AS in_use;
"""

DELETE_QUEUE_SQL = """
DELETE FROM queues_custom
WHERE name = %(name)s
RETURNING name, musicclass, moh_file_name;
"""


def list_queues(connection: psycopg.Connection) -> list[dict]:
    with connection.cursor(row_factory=dict_row) as cursor:
        cursor.execute(LIST_QUEUES_SQL)
        queues = list(cursor.fetchall())
        for queue in queues:
            cursor.execute(LIST_QUEUE_MEMBERS_SQL, {"queue_id": queue["id"]})
            queue["members"] = [row["extension"] for row in cursor.fetchall()]
    return queues


def create_queue(connection: psycopg.Connection, payload: QueueCreate) -> dict:
    values = payload.model_dump()
    with connection.cursor(row_factory=dict_row) as cursor:
        cursor.execute(UPSERT_QUEUE_SQL, values)
        record = cursor.fetchone()
        cursor.execute(GET_QUEUE_ID_SQL, {"name": values["name"]})
        queue_id = cursor.fetchone()["id"]
        cursor.execute(DELETE_QUEUE_MEMBERS_SQL, {"queue_id": queue_id})
        for member_order, member in enumerate(values["members"], start=1):
            cursor.execute(
                INSERT_QUEUE_MEMBER_SQL,
                {"queue_id": queue_id, "extension": member, "member_order": member_order},
            )
        record["members"] = values["members"]
    return record


def delete_queue(connection: psycopg.Connection, name: str) -> bool:
    with connection.cursor(row_factory=dict_row) as cursor:
        cursor.execute("SELECT id, extension FROM queues_custom WHERE name = %(name)s", {"name": name})
        row = cursor.fetchone()
        if not row:
            return False
        cursor.execute(QUEUE_USAGE_SQL, {"extension": row["extension"]})
        if cursor.fetchone()["in_use"]:
            raise ValueError("Queue is still used by an inbound route or IVR option.")
        cursor.execute(DELETE_QUEUE_MEMBERS_SQL, {"queue_id": row["id"]})
        cursor.execute(DELETE_QUEUE_SQL, {"name": name})
        deleted = cursor.fetchone()
    if deleted:
        delete_queue_moh(deleted["musicclass"], deleted["moh_file_name"])
    return bool(deleted)
