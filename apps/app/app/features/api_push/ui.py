from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
import json
import psycopg

from app.core.db import get_connection
from app.models.api_push import ApiPushSettingsPayload
from app.services.api_push import (
    get_api_push_settings,
    get_test_receiver_urls,
    list_dead_letters,
    list_test_payloads,
    run_push_cycle,
    save_api_push_settings,
)
from app.web import render_template


router = APIRouter(tags=["api-push"])


@router.get("/api-push", response_class=HTMLResponse)
def api_push_page(
    request: Request,
    connection: psycopg.Connection = Depends(get_connection),
) -> HTMLResponse:
    settings = get_api_push_settings(connection)
    result = request.query_params.get("result", "")
    detail = request.query_params.get("detail", "")
    run_output = request.query_params.get("run_output", "")
    return render_template(
        request,
        "api_push/index.html",
        page_title="API Push",
        page_description="API push now has its own feature for webhook settings, test receivers, retry state, and dead-letter visibility.",
        active_nav="/api-push",
        settings=settings,
        result=result,
        detail=detail,
        run_output=run_output,
        dead_letters=list_dead_letters(connection),
        test_payloads=list_test_payloads(connection),
        test_urls=get_test_receiver_urls(str(request.base_url).rstrip("/")),
        settings_json=json.dumps(settings, indent=2),
    )


@router.post("/api-push/settings")
def save_api_push_settings_from_ui(
    enabled_raw: str | None = Form(default=None),
    call_logs_url: str = Form(default=""),
    callbacks_url: str = Form(default=""),
    public_base_url: str = Form(default=""),
    api_key: str = Form(default=""),
    timeout_seconds: int = Form(default=10),
    poll_interval_seconds: int = Form(default=30),
    batch_limit: int = Form(default=200),
    verify_ssl_raw: str | None = Form(default=None),
    connection: psycopg.Connection = Depends(get_connection),
) -> RedirectResponse:
    payload = ApiPushSettingsPayload(
        enabled=enabled_raw is not None,
        call_logs_url=call_logs_url or None,
        callbacks_url=callbacks_url or None,
        public_base_url=public_base_url or None,
        api_key=api_key or None,
        timeout_seconds=timeout_seconds,
        poll_interval_seconds=poll_interval_seconds,
        verify_ssl=verify_ssl_raw is not None,
        batch_limit=batch_limit,
    )
    save_api_push_settings(connection, payload)
    params = urlencode({"result": "success", "detail": "API push settings saved."})
    return RedirectResponse(url=f"/api-push?{params}", status_code=303)


@router.post("/api-push/run")
def run_api_push_from_ui(
    connection: psycopg.Connection = Depends(get_connection),
) -> RedirectResponse:
    result = run_push_cycle(connection)
    params = urlencode(
        {
            "result": "success",
            "detail": "Push cycle finished.",
            "run_output": json.dumps(result, indent=2),
        }
    )
    return RedirectResponse(url=f"/api-push?{params}", status_code=303)
