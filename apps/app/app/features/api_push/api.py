from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
import psycopg
from starlette import status

from app.core.db import get_connection
from app.models.api_push import ApiPushSettingsPayload
from app.services.api_push import (
    get_api_push_settings,
    get_test_receiver_urls,
    list_dead_letters,
    list_test_payloads,
    record_test_payload,
    run_push_cycle,
    save_api_push_settings,
)


router = APIRouter(tags=["api-push"])


@router.get("/api-push/settings")
def get_settings_api(
    request: Request,
    connection: psycopg.Connection = Depends(get_connection),
) -> dict[str, object]:
    base_url = str(request.base_url).rstrip("/")
    settings = get_api_push_settings(connection)
    pending = {
        "dead_letters": len(list_dead_letters(connection)),
        "test_payloads": len(list_test_payloads(connection)),
    }
    return {
        "status": "ok",
        "settings": settings,
        "pending": pending,
        "test_webhook": get_test_receiver_urls(base_url),
    }


@router.post("/api-push/settings")
def post_settings_api(
    payload: ApiPushSettingsPayload,
    connection: psycopg.Connection = Depends(get_connection),
) -> dict[str, object]:
    return {"status": "ok", "settings": save_api_push_settings(connection, payload)}


@router.post("/api-push/run")
def run_push_api(
    connection: psycopg.Connection = Depends(get_connection),
) -> dict[str, object]:
    return run_push_cycle(connection)


@router.get("/api-push/dead-letters")
def get_dead_letters_api(
    connection: psycopg.Connection = Depends(get_connection),
) -> dict[str, object]:
    return {"status": "ok", "rows": list_dead_letters(connection)}


@router.get("/api-push/test-payloads")
def get_test_payloads_api(
    request: Request,
    connection: psycopg.Connection = Depends(get_connection),
) -> dict[str, object]:
    base_url = str(request.base_url).rstrip("/")
    return {
        "status": "ok",
        "rows": list_test_payloads(connection),
        "urls": get_test_receiver_urls(base_url),
    }


@router.post("/api-push/test-receiver/{entity_type}")
async def api_push_test_receiver(
    entity_type: str,
    request: Request,
    connection: psycopg.Connection = Depends(get_connection),
) -> dict[str, str]:
    if entity_type not in {"call_logs", "callbacks"}:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown entity type.")
    payload = await request.json()
    record_test_payload(
        connection,
        entity_type=entity_type,
        source_ip=request.client.host if request.client else None,
        api_key=request.headers.get("X-API-Key"),
        headers_json=dict(request.headers.items()),
        payload_json=payload,
    )
    return {"status": "ok"}
