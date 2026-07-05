from urllib.parse import urlencode
from io import BytesIO
from pathlib import Path
import zipfile

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, Response
from fastapi.responses import RedirectResponse
import json
import psycopg

from app.core.db import get_connection
from app.core.settings import get_settings
from app.services.extensions import list_extensions
from app.services.softphone import (
    build_softphone_bootstrap,
    get_softphone_settings,
    resolve_current_webphone,
    save_softphone_settings,
    set_softphone_dnd,
)
from app.web import render_template


router = APIRouter(tags=["softphone"])

WEBPHONE_EXTENSION_EXCLUDES = {"__pycache__", ".DS_Store"}


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
            bootstrap = build_softphone_bootstrap(
                connection,
                selected_extension,
                request_host=request.headers.get("host", ""),
                request_scheme=_request_scheme(request),
            )
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
    stun_urls: str = Form(default=""),
    turn_urls: str = Form(default=""),
    turn_username: str = Form(default=""),
    turn_credential: str = Form(default=""),
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
        stun_urls=stun_urls or None,
        turn_urls=turn_urls or None,
        turn_username=turn_username or None,
        turn_credential=turn_credential or None,
        note=note or None,
    )
    save_softphone_settings(connection, payload)
    return RedirectResponse(url="/softphone", status_code=303)


@router.post("/softphone/dnd/{extension}")
def set_softphone_dnd_from_ui(
    request: Request,
    extension: str,
    enabled_raw: str | None = Form(default=None),
    connection: psycopg.Connection = Depends(get_connection),
) -> Response:
    current_user = getattr(request.state, "current_user", None) or {}
    own_extension = str(current_user.get("extension") or current_user.get("username") or "")
    if current_user.get("role") == "user" and extension != own_extension:
        return PlainTextResponse("You can only change your own webphone.", status_code=403)
    set_softphone_dnd(connection, extension, enabled_raw is not None)
    params = urlencode({"extension": extension})
    return RedirectResponse(url=f"/softphone?{params}", status_code=303)


@router.get("/softphone/extension/download")
def download_webphone_extension() -> Response:
    extension_dir = _webphone_extension_dir()
    archive_root = "omnipbx-webphone-extension"
    archive = BytesIO()
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as zip_file:
        for path in sorted(extension_dir.rglob("*")):
            if not path.is_file() or any(part in WEBPHONE_EXTENSION_EXCLUDES for part in path.parts):
                continue
            zip_file.write(path, Path(archive_root) / path.relative_to(extension_dir))
    archive.seek(0)
    return Response(
        archive.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="omnipbx-webphone-extension.zip"'},
    )


def _webphone_extension_dir() -> Path:
    host_path = Path(get_settings().host_project_path) / "third_party" / "web-softphone-demo"
    if host_path.exists():
        return host_path
    return Path(__file__).resolve().parents[5] / "third_party" / "web-softphone-demo"


@router.get("/webphone/detached", response_class=HTMLResponse)
def detached_webphone_page(
    request: Request,
    extension: str = "",
    connection: psycopg.Connection = Depends(get_connection),
) -> HTMLResponse:
    current_user = getattr(request.state, "current_user", None) or {}
    role = str(current_user.get("role") or "")
    bootstrap = resolve_current_webphone(
        connection,
        username=str(current_user.get("extension") or current_user.get("username") or ""),
        extension=extension,
        request_host=request.headers.get("host", ""),
        request_scheme=_request_scheme(request),
        can_switch=role in {"owner", "admin"},
    )
    return render_template(
        request,
        "softphone/detached.html",
        page_title="Webphone",
        page_description="Browser phone",
        active_nav="/softphone",
        show_shell=False,
        show_notifications=False,
        show_profile_avatar=False,
        bootstrap=bootstrap,
        page_js=["/static/vendor/sip-simple-user.min.js", "/static/vendor/jssip.min.js", "/static/js/webphone.js"],
        page_css=["/static/css/webphone.css"],
    )


def _request_scheme(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-proto", "").split(",", 1)[0].strip()
    return forwarded or request.url.scheme
