from __future__ import annotations

import hashlib
import json
import socket
import ssl
import threading
import time
from datetime import datetime, timedelta
from urllib import error as urllib_error
from urllib import request as urllib_request

import psycopg
from psycopg.rows import dict_row

from app.core.settings import get_settings
from app.models.api_push import ApiPushSettingsPayload
from app.services.call_logs import list_call_logs, list_callback_worklist


HOSTNAME = socket.gethostname()
ENTITY_TYPES = ("call_logs", "callbacks")
_worker_lock = threading.Lock()
_worker_started = False


def get_api_push_settings(connection: psycopg.Connection) -> dict:
    with connection.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT enabled, call_logs_url, callbacks_url, public_base_url, api_key,
                   timeout_seconds, poll_interval_seconds, verify_ssl, batch_limit
            FROM api_push_settings
            WHERE id = 1
            """
        )
        return dict(cursor.fetchone())


def save_api_push_settings(connection: psycopg.Connection, payload: ApiPushSettingsPayload) -> dict:
    values = payload.model_dump()
    with connection.cursor() as cursor:
        cursor.execute(
            """
            UPDATE api_push_settings
            SET
                enabled = %(enabled)s,
                call_logs_url = %(call_logs_url)s,
                callbacks_url = %(callbacks_url)s,
                public_base_url = %(public_base_url)s,
                api_key = %(api_key)s,
                timeout_seconds = %(timeout_seconds)s,
                poll_interval_seconds = %(poll_interval_seconds)s,
                verify_ssl = %(verify_ssl)s,
                batch_limit = %(batch_limit)s,
                updated_at = NOW()
            WHERE id = 1
            """,
            values,
        )
    return get_api_push_settings(connection)


def list_dead_letters(connection: psycopg.Connection) -> list[dict]:
    with connection.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT entity_type, entity_key, target_url, retry_count, error_message,
                   TO_CHAR(last_attempt_at, 'YYYY-MM-DD HH24:MI:SS') AS last_attempt_at
            FROM api_push_dead_letters
            WHERE resolved = FALSE
            ORDER BY updated_at DESC
            LIMIT 100
            """
        )
        return list(cursor.fetchall())


def list_test_payloads(connection: psycopg.Connection) -> list[dict]:
    with connection.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT entity_type, source_ip, payload_json::text AS payload_json,
                   TO_CHAR(created_at, 'YYYY-MM-DD HH24:MI:SS') AS created_at
            FROM api_push_test_payloads
            ORDER BY created_at DESC
            LIMIT 100
            """
        )
        return list(cursor.fetchall())


def record_test_payload(
    connection: psycopg.Connection,
    *,
    entity_type: str,
    source_ip: str | None,
    api_key: str | None,
    headers_json: dict,
    payload_json: dict,
) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO api_push_test_payloads (entity_type, source_ip, api_key, headers_json, payload_json)
            VALUES (%(entity_type)s, %(source_ip)s, %(api_key)s, %(headers_json)s::jsonb, %(payload_json)s::jsonb)
            """,
            {
                "entity_type": entity_type,
                "source_ip": source_ip,
                "api_key": api_key,
                "headers_json": json.dumps(headers_json),
                "payload_json": json.dumps(payload_json),
            },
        )


def run_push_cycle(connection: psycopg.Connection) -> dict[str, object]:
    settings = get_api_push_settings(connection)
    results: dict[str, object] = {"status": "ok", "entities": {}}
    if not settings["enabled"]:
        return {"status": "ok", "message": "API push is disabled.", "entities": {}}

    for entity_type in ENTITY_TYPES:
        target_url = settings[f"{entity_type}_url"]
        if not target_url:
            results["entities"][entity_type] = {"status": "skipped", "detail": "No target URL configured."}
            continue

        records = _build_records(connection, entity_type, int(settings["batch_limit"]), settings.get("public_base_url"))
        pending = _select_pending_records(connection, entity_type, records)
        if not pending:
            results["entities"][entity_type] = {"status": "idle", "count": 0}
            continue

        ok, detail = _push_records(
            target_url=target_url,
            api_key=settings.get("api_key"),
            timeout_seconds=int(settings["timeout_seconds"]),
            verify_ssl=bool(settings["verify_ssl"]),
            entity_type=entity_type,
            records=pending,
        )
        if ok:
            _upsert_push_state(connection, entity_type, pending, status="success")
            results["entities"][entity_type] = {"status": "success", "count": len(pending)}
        else:
            retry_count = _next_retry_count(connection, entity_type, pending)
            dead_letter = retry_count >= 5
            _upsert_push_state(connection, entity_type, pending, status="error", error_message=detail, retry_count=retry_count, dead_letter=dead_letter)
            if dead_letter:
                _record_dead_letters(connection, entity_type, target_url, pending, detail, retry_count)
            results["entities"][entity_type] = {
                "status": "error",
                "count": len(pending),
                "detail": detail,
                "dead_letter": dead_letter,
            }

    results["pending"] = {
        "dead_letters": len(list_dead_letters(connection)),
        "test_payloads": len(list_test_payloads(connection)),
    }
    return results


def start_api_push_worker() -> None:
    global _worker_started
    with _worker_lock:
        if _worker_started:
            return
        thread = threading.Thread(target=_worker_loop, daemon=True, name="omnipbx-api-push")
        thread.start()
        _worker_started = True


def get_test_receiver_urls(base_url: str) -> dict[str, str]:
    normalized = base_url.rstrip("/")
    return {
        "call_logs_url": f"{normalized}/api-push/test-receiver/call_logs",
        "callbacks_url": f"{normalized}/api-push/test-receiver/callbacks",
    }


def _worker_loop() -> None:
    settings = get_settings()
    while True:
        sleep_seconds = 30
        try:
            with psycopg.connect(settings.db_dsn, autocommit=True) as connection:
                current = get_api_push_settings(connection)
                sleep_seconds = int(current.get("poll_interval_seconds") or 30)
                if current.get("enabled"):
                    run_push_cycle(connection)
        except Exception:
            sleep_seconds = 30
        time.sleep(max(5, min(300, sleep_seconds)))


def _build_records(connection: psycopg.Connection, entity_type: str, limit: int, public_base_url: str | None) -> list[dict]:
    if entity_type == "call_logs":
        return list_call_logs(connection, limit=limit)["rows"]
    return list_callback_worklist(connection, open_only=False, limit=limit)["rows"]


def _build_payload_hash(record: dict) -> str:
    payload = {key: value for key, value in record.items() if key != "recording_url"}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def _select_pending_records(connection: psycopg.Connection, entity_type: str, records: list[dict]) -> list[dict]:
    state_map = _load_state_map(connection, entity_type)
    pending: list[dict] = []
    now = datetime.now()
    for record in records:
        entity_key = str(record.get("linkedid") or record.get("uniqueid"))
        payload_hash = _build_payload_hash(record)
        state = state_map.get(entity_key)
        if state:
            if state["dead_letter"] and state["payload_hash"] == payload_hash:
                continue
            if state["next_retry_at"] and state["next_retry_at"] > now:
                continue
            if state["payload_hash"] == payload_hash and state["last_status"] == "success":
                continue
        enriched = dict(record)
        enriched["_entity_key"] = entity_key
        enriched["_payload_hash"] = payload_hash
        pending.append(enriched)
    return pending


def _load_state_map(connection: psycopg.Connection, entity_type: str) -> dict[str, dict]:
    with connection.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT entity_key, payload_hash, last_status, retry_count, dead_letter, next_retry_at
            FROM api_push_state
            WHERE entity_type = %(entity_type)s
            """,
            {"entity_type": entity_type},
        )
        return {row["entity_key"]: dict(row) for row in cursor.fetchall()}


def _push_records(
    *,
    target_url: str,
    api_key: str | None,
    timeout_seconds: int,
    verify_ssl: bool,
    entity_type: str,
    records: list[dict],
) -> tuple[bool, str]:
    payload = {
        "source": "omnipbx",
        "hostname": HOSTNAME,
        "entity": entity_type,
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "count": len(records),
        "records": [{k: v for k, v in row.items() if not k.startswith("_")} for row in records],
    }
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["X-API-Key"] = api_key
    request = urllib_request.Request(
        target_url,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    context = None if verify_ssl else ssl._create_unverified_context()
    try:
        with urllib_request.urlopen(request, timeout=timeout_seconds, context=context) as response:
            body = response.read().decode("utf-8", errors="replace")
            return 200 <= response.status < 300, body or f"HTTP {response.status}"
    except urllib_error.HTTPError as exc:
        return False, exc.read().decode("utf-8", errors="replace") or f"HTTP {exc.code}"
    except Exception as exc:
        return False, str(exc)


def _upsert_push_state(
    connection: psycopg.Connection,
    entity_type: str,
    records: list[dict],
    *,
    status: str,
    error_message: str | None = None,
    retry_count: int = 0,
    dead_letter: bool = False,
) -> None:
    next_retry_at = None
    last_pushed_at = None
    if status == "error" and not dead_letter:
        next_retry_at = datetime.now() + timedelta(seconds=min(300, max(10, 30 * max(1, retry_count))))
    if status == "success":
        last_pushed_at = datetime.now()
    with connection.cursor() as cursor:
        for record in records:
            cursor.execute(
                """
                INSERT INTO api_push_state (
                    entity_type, entity_key, payload_hash, last_status, retry_count, dead_letter, last_error, next_retry_at, last_pushed_at
                ) VALUES (
                    %(entity_type)s, %(entity_key)s, %(payload_hash)s, %(last_status)s, %(retry_count)s, %(dead_letter)s,
                    %(last_error)s, %(next_retry_at)s, %(last_pushed_at)s
                )
                ON CONFLICT (entity_type, entity_key) DO UPDATE
                SET
                    payload_hash = EXCLUDED.payload_hash,
                    last_status = EXCLUDED.last_status,
                    retry_count = EXCLUDED.retry_count,
                    dead_letter = EXCLUDED.dead_letter,
                    last_error = EXCLUDED.last_error,
                    next_retry_at = EXCLUDED.next_retry_at,
                    last_pushed_at = CASE WHEN EXCLUDED.last_status = 'success' THEN NOW() ELSE api_push_state.last_pushed_at END,
                    updated_at = NOW()
                """,
                {
                    "entity_type": entity_type,
                    "entity_key": record["_entity_key"],
                    "payload_hash": record["_payload_hash"],
                    "last_status": status,
                    "retry_count": retry_count,
                    "dead_letter": dead_letter,
                    "last_error": error_message,
                    "next_retry_at": next_retry_at,
                    "last_pushed_at": last_pushed_at,
                },
            )


def _next_retry_count(connection: psycopg.Connection, entity_type: str, records: list[dict]) -> int:
    if not records:
        return 0
    first = records[0]["_entity_key"]
    with connection.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT retry_count
            FROM api_push_state
            WHERE entity_type = %(entity_type)s AND entity_key = %(entity_key)s
            """,
            {"entity_type": entity_type, "entity_key": first},
        )
        row = cursor.fetchone()
    return int(row["retry_count"]) + 1 if row else 1


def _record_dead_letters(
    connection: psycopg.Connection,
    entity_type: str,
    target_url: str,
    records: list[dict],
    error_message: str,
    retry_count: int,
) -> None:
    with connection.cursor() as cursor:
        for record in records:
            cursor.execute(
                """
                INSERT INTO api_push_dead_letters (
                    entity_type, entity_key, target_url, payload_hash, payload_json, error_message, retry_count, last_attempt_at, resolved, updated_at
                ) VALUES (
                    %(entity_type)s, %(entity_key)s, %(target_url)s, %(payload_hash)s, %(payload_json)s::jsonb,
                    %(error_message)s, %(retry_count)s, NOW(), FALSE, NOW()
                )
                ON CONFLICT (entity_type, entity_key) DO UPDATE
                SET
                    target_url = EXCLUDED.target_url,
                    payload_hash = EXCLUDED.payload_hash,
                    payload_json = EXCLUDED.payload_json,
                    error_message = EXCLUDED.error_message,
                    retry_count = EXCLUDED.retry_count,
                    last_attempt_at = NOW(),
                    resolved = FALSE,
                    updated_at = NOW()
                """,
                {
                    "entity_type": entity_type,
                    "entity_key": record["_entity_key"],
                    "target_url": target_url,
                    "payload_hash": record["_payload_hash"],
                    "payload_json": json.dumps({k: v for k, v in record.items() if not k.startswith("_")}),
                    "error_message": error_message,
                    "retry_count": retry_count,
                },
            )
