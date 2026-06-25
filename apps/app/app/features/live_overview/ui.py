import asyncio
import json

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, StreamingResponse
import psycopg

from app.core.db import get_connection
from app.features.live_overview.service import collect_live_overview, start_supervisor_action
from app.services.live_events import live_event_hub
from app.services.softphone import resolve_current_webphone
from app.services.trunks import list_trunks
from app.web import render_template


router = APIRouter(tags=["live-overview"])


@router.get("/live-overview", response_class=HTMLResponse)
def live_overview_page(
    request: Request,
    connection: psycopg.Connection = Depends(get_connection),
) -> HTMLResponse:
    overview = _initial_overview(connection)
    current_user = getattr(request.state, "current_user", None) or {}
    webphone = _current_webphone(connection, request, current_user)
    supervisor_extension = str((webphone.get("config") or {}).get("extension") or "")
    return render_template(
        request,
        "live_overview/index.html",
        page_title="Live Overview",
        page_description="",
        active_nav="/live-overview",
        overview=overview,
        supervisor_extension=supervisor_extension,
        dashboard_notifications=[],
        page_css=["/static/css/live_overview.css"],
        page_js=["/static/js/live_overview.js"],
    )


@router.get("/live-overview/data")
def live_overview_data(
    connection: psycopg.Connection = Depends(get_connection),
) -> dict[str, object]:
    return collect_live_overview(connection)


@router.get("/live-overview/events")
async def live_overview_events(request: Request) -> StreamingResponse:
    async def event_stream():
        version = live_event_hub.version
        overview = live_event_hub.get_snapshot() or _empty_overview()
        overview["event"] = "snapshot"
        yield f"data: {json.dumps(overview, default=str)}\n\n"

        while not await request.is_disconnected():
            next_version, event_name = await asyncio.to_thread(live_event_hub.wait_for_change, version, 2.0)
            if await request.is_disconnected():
                break
            if next_version == version:
                yield ": keep-alive\n\n"
                continue
            version = next_version
            overview = live_event_hub.get_snapshot() or _empty_overview()
            overview["event"] = event_name
            yield f"data: {json.dumps(overview, default=str)}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store"},
    )


@router.post("/live-overview/supervisor-action")
def supervisor_action(
    request: Request,
    supervisor_extension: str = Form(default=""),
    channel_id: str = Form(...),
    action: str = Form(...),
    connection: psycopg.Connection = Depends(get_connection),
) -> dict[str, str | bool]:
    current_user = getattr(request.state, "current_user", None) or {}
    webphone = _current_webphone(
        connection,
        request,
        current_user,
        selected_extension=supervisor_extension,
    )
    config = webphone.get("config") or {}
    resolved_extension = str(config.get("extension") or "")
    if not webphone.get("available") or not resolved_extension:
        return {
            "ok": False,
            "message": "Your logged-in account does not have a registered webphone extension.",
        }
    return start_supervisor_action(
        connection,
        supervisor_extension=resolved_extension,
        channel_id=channel_id,
        action=action,
    )


def _current_webphone(
    connection: psycopg.Connection,
    request: Request,
    current_user: dict,
    *,
    selected_extension: str = "",
) -> dict:
    role = str(current_user.get("role") or "")
    can_switch = role in {"owner", "admin"}
    return resolve_current_webphone(
        connection,
        username=str(current_user.get("extension") or current_user.get("username") or ""),
        extension=selected_extension,
        request_host=request.headers.get("host", ""),
        request_scheme=_request_scheme(request),
        can_switch=can_switch,
    )


def _request_scheme(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-proto", "").split(",", 1)[0].strip()
    return forwarded or request.url.scheme


def _initial_overview(connection: psycopg.Connection) -> dict[str, object]:
    trunks = [
        {
            "name": trunk["name"],
            "provider": trunk.get("provider_name") or trunk.get("host") or "-",
            "status": "Warning" if trunk.get("enabled") else "Offline",
            "status_class": "warn" if trunk.get("enabled") else "offline",
            "active_calls": 0,
            "last_registered": "-",
            "message": "Loading live status",
        }
        for trunk in list_trunks(connection)
    ]
    return {
        "summary": {
            "active_calls": 0,
            "active_users": 0,
            "trunks_online": 0,
            "system_status": "Loading",
        },
        "active_calls": [],
        "active_users": [],
        "trunks": trunks,
        "system_status": {
            "label": "Loading",
            "class": "warning",
            "message": "Live status is loading.",
        },
        "notifications": [],
    }


def _empty_overview() -> dict[str, object]:
    return {
        "summary": {
            "active_calls": 0,
            "active_users": 0,
            "trunks_online": 0,
            "system_status": "Loading",
        },
        "active_calls": [],
        "active_users": [],
        "trunks": [],
        "system_status": {
            "label": "Loading",
            "class": "warning",
            "message": "Live status is loading.",
        },
        "notifications": [],
    }
