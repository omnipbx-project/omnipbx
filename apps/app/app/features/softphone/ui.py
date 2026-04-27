from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse
from fastapi.responses import RedirectResponse
import json
import psycopg

from app.core.db import get_connection
from app.services.extensions import list_extensions
from app.services.softphone import (
    build_softphone_bootstrap,
    get_softphone_settings,
    save_softphone_settings,
    set_softphone_dnd,
)
from app.web import render_template


router = APIRouter(tags=["softphone"])


@router.get("/softphone", response_class=HTMLResponse)
def softphone_page(
    request: Request,
    extension: str = "",
    connection: psycopg.Connection = Depends(get_connection),
) -> HTMLResponse:
    settings = get_softphone_settings(connection)
    extensions = list_extensions(connection)
    selected_extension = extension or (extensions[0]["extension"] if extensions else "")
    bootstrap = None
    if selected_extension:
        try:
            bootstrap = build_softphone_bootstrap(connection, selected_extension)
        except ValueError:
            bootstrap = None
    return render_template(
        request,
        "softphone/index.html",
        page_title="Softphone",
        page_description="Softphone now has its own feature for WebRTC settings, extension bootstrap payloads, and per-extension DND control.",
        active_nav="/softphone",
        settings=settings,
        extensions=extensions,
        selected_extension=selected_extension,
        bootstrap=bootstrap,
        bootstrap_json=json.dumps(bootstrap, indent=2) if bootstrap else "",
    )


@router.post("/softphone/settings")
def save_softphone_settings_from_ui(
    enabled_raw: str | None = Form(default=None),
    websocket_url: str = Form(default=""),
    sip_domain: str = Form(default=""),
    display_name_prefix: str = Form(default=""),
    public_host: str = Form(default=""),
    note: str = Form(default=""),
    connection: psycopg.Connection = Depends(get_connection),
) -> RedirectResponse:
    from app.models.softphone import SoftphoneSettingsPayload

    payload = SoftphoneSettingsPayload(
        enabled=enabled_raw is not None,
        websocket_url=websocket_url or None,
        sip_domain=sip_domain or None,
        display_name_prefix=display_name_prefix or None,
        public_host=public_host or None,
        note=note or None,
    )
    save_softphone_settings(connection, payload)
    return RedirectResponse(url="/softphone", status_code=303)


@router.post("/softphone/dnd/{extension}")
def set_softphone_dnd_from_ui(
    extension: str,
    enabled_raw: str | None = Form(default=None),
    connection: psycopg.Connection = Depends(get_connection),
) -> RedirectResponse:
    set_softphone_dnd(connection, extension, enabled_raw is not None)
    params = urlencode({"extension": extension})
    return RedirectResponse(url=f"/softphone?{params}", status_code=303)
