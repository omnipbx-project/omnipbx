import asyncio
import json

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, StreamingResponse
import psycopg

from app.core.db import get_connection
from app.core.settings import get_settings
from app.features.live_overview.service import collect_live_overview, start_supervisor_action
from app.services.live_events import live_event_hub
from app.services.trunks import list_trunks
from app.web import render_template


router = APIRouter(tags=["live-overview"])


@router.get("/live-overview", response_class=HTMLResponse)
def live_overview_page(
    request: Request,
    connection: psycopg.Connection = Depends(get_connection),
) -> HTMLResponse:
    overview = _initial_overview(connection)
    return render_template(
        request,
        "live_overview/index.html",
        page_title="Live Overview",
        page_description="",
        active_nav="/live-overview",
        overview=overview,
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
    settings = get_settings()

    async def event_stream():
        version = live_event_hub.version
        overview = await asyncio.to_thread(_collect_overview_snapshot, settings.db_dsn)
        overview["event"] = "snapshot"
        yield f"data: {json.dumps(overview, default=str)}\n\n"

        while not await request.is_disconnected():
            version, event_name = await asyncio.to_thread(live_event_hub.wait_for_change, version)
            overview = await asyncio.to_thread(_collect_overview_snapshot, settings.db_dsn)
            overview["event"] = event_name
            yield f"data: {json.dumps(overview, default=str)}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store"},
    )


@router.post("/live-overview/supervisor-action")
def supervisor_action(
    supervisor_extension: str = Form(...),
    channel_id: str = Form(...),
    action: str = Form(...),
    connection: psycopg.Connection = Depends(get_connection),
) -> dict[str, str | bool]:
    return start_supervisor_action(
        connection,
        supervisor_extension=supervisor_extension,
        channel_id=channel_id,
        action=action,
    )


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


def _collect_overview_snapshot(db_dsn: str) -> dict[str, object]:
    with psycopg.connect(db_dsn, autocommit=True) as connection:
        return collect_live_overview(connection)
