from urllib.parse import urlencode
import socket

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
import psycopg
from pydantic import ValidationError
from starlette import status

from app.core.db import get_connection
from app.features.live_overview.service import collect_live_overview
from app.models.trunk import TrunkCreate
from app.services.asterisk import sync_asterisk_config
from app.services.trunks import create_trunk, delete_trunk, list_trunks, update_trunk, update_trunk_enabled
from app.web import render_template


router = APIRouter(tags=["trunks"])

PROTOCOL_TO_TRANSPORT = {
    "auto": "transport-udp",
    "udp": "transport-udp",
    "tcp": "transport-tcp",
    "tls": "transport-tls",
    "wss": "transport-wss",
}

DEFAULT_PORTS = {
    "auto": 5060,
    "udp": 5060,
    "tcp": 5060,
    "tls": 5061,
    "wss": 443,
}


@router.get("/trunks", response_class=HTMLResponse)
def trunks_page(
    request: Request,
    connection: psycopg.Connection = Depends(get_connection),
) -> HTMLResponse:
    trunks = list_trunks(connection)
    overview = collect_live_overview(connection)
    trunk_statuses = {trunk["name"]: trunk for trunk in overview["trunks"]}
    result = request.query_params.get("result", "")
    detail = request.query_params.get("detail", "")
    return render_template(
        request,
        "trunks/index.html",
        page_title="Trunks",
        page_description="",
        active_nav="/trunks",
        trunks=trunks,
        trunk_statuses=trunk_statuses,
        result=result,
        detail=detail,
        dashboard_notifications=overview["notifications"],
        topbar_search={"placeholder": "Search trunk or provider...", "label": "Search trunk or provider"},
        topbar_action={"id": "open-trunk-modal", "label": "+ Add Trunk"},
        show_notifications=True,
        show_profile_avatar=True,
        page_css=["/static/css/trunks.css"],
        page_js=["/static/js/trunks.js"],
    )


@router.post("/trunks/create")
def create_trunk_from_ui(
    name: str = Form(...),
    provider_name: str = Form(default=""),
    main_number: str = Form(default=""),
    host: str = Form(...),
    username: str = Form(default=""),
    password: str = Form(default=""),
    protocol: str = Form(default="auto"),
    port: str = Form(default=""),
    connection: psycopg.Connection = Depends(get_connection),
) -> RedirectResponse:
    try:
        protocol_value = _normalize_protocol(protocol)
        payload = TrunkCreate(
            name=name,
            provider_name=provider_name or None,
            main_number=main_number or None,
            host=_host_with_port(host, port, protocol_value),
            username=username or None,
            password=password or None,
            transport=PROTOCOL_TO_TRANSPORT[protocol_value],
            register_enabled=bool(username and password),
            match_ip=None,
            enabled=True,
        )
        record = create_trunk(connection, payload)
    except (ValidationError, psycopg.errors.UniqueViolation, ValueError) as exc:
        params = urlencode({"result": "error", "detail": str(exc)})
        return RedirectResponse(url=f"/trunks?{params}", status_code=status.HTTP_303_SEE_OTHER)

    reload_result = sync_asterisk_config(connection)
    params = urlencode(
        {
            "result": "success",
            "detail": (
                f"Created trunk {record['name']}. "
                f"Asterisk reload status: {reload_result['status']}."
            ),
        }
    )
    return RedirectResponse(url=f"/trunks?{params}", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/trunks/{name}/update")
def update_trunk_from_ui(
    name: str,
    new_name: str = Form(...),
    provider_name: str = Form(default=""),
    main_number: str = Form(default=""),
    host: str = Form(...),
    username: str = Form(default=""),
    password: str = Form(default=""),
    protocol: str = Form(default="auto"),
    port: str = Form(default=""),
    connection: psycopg.Connection = Depends(get_connection),
) -> RedirectResponse:
    try:
        protocol_value = _normalize_protocol(protocol)
        existing = next((item for item in list_trunks(connection) if item["name"] == name), None)
        if not existing:
            params = urlencode({"result": "error", "detail": f"Trunk {name} was not found."})
            return RedirectResponse(url=f"/trunks?{params}", status_code=status.HTTP_303_SEE_OTHER)
        username_value = username or existing.get("username")
        password_value = password or existing.get("password")
        payload = TrunkCreate(
            name=new_name,
            provider_name=provider_name or None,
            main_number=main_number or existing.get("main_number"),
            host=_host_with_port(host, port, protocol_value),
            username=username_value or None,
            password=password_value or None,
            transport=PROTOCOL_TO_TRANSPORT[protocol_value],
            register_enabled=bool(username_value and password_value),
            match_ip=None,
            enabled=bool(existing.get("enabled")),
        )
        record = update_trunk(connection, name, payload)
    except (ValidationError, psycopg.errors.UniqueViolation, ValueError) as exc:
        params = urlencode({"result": "error", "detail": str(exc)})
        return RedirectResponse(url=f"/trunks?{params}", status_code=status.HTTP_303_SEE_OTHER)

    if not record:
        params = urlencode({"result": "error", "detail": f"Trunk {name} was not found."})
        return RedirectResponse(url=f"/trunks?{params}", status_code=status.HTTP_303_SEE_OTHER)

    reload_result = sync_asterisk_config(connection)
    params = urlencode(
        {
            "result": "success",
            "detail": f"Updated trunk {record['name']}. Asterisk reload status: {reload_result['status']}.",
        }
    )
    return RedirectResponse(url=f"/trunks?{params}", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/trunks/test")
def test_trunk_connection(
    host: str = Form(...),
    protocol: str = Form(default="auto"),
    port: str = Form(default=""),
) -> dict[str, str | bool]:
    protocol_value = _normalize_protocol(protocol)
    target_host, target_port = _split_host_port(_host_with_port(host, port, protocol_value), protocol_value)
    try:
        if protocol_value in {"udp", "auto"}:
            socket.getaddrinfo(target_host, target_port)
            return {"ok": True, "message": f"Server address looks reachable on port {target_port}."}
        with socket.create_connection((target_host, target_port), timeout=4):
            return {"ok": True, "message": f"Connected to {target_host}:{target_port}."}
    except OSError as exc:
        return {"ok": False, "message": f"Could not reach {target_host}:{target_port}. {exc}"}


@router.post("/trunks/{name}/test")
def test_saved_trunk(
    name: str,
    connection: psycopg.Connection = Depends(get_connection),
) -> dict[str, str | bool]:
    trunk = next((item for item in list_trunks(connection) if item["name"] == name), None)
    if not trunk:
        return {"ok": False, "message": f"Trunk {name} was not found."}
    protocol = _protocol_from_transport(trunk["transport"])
    target_host, target_port = _split_host_port(trunk["host"], protocol)
    try:
        if protocol in {"udp", "auto"}:
            socket.getaddrinfo(target_host, target_port)
            return {"ok": True, "message": f"{name} server address looks reachable."}
        with socket.create_connection((target_host, target_port), timeout=4):
            return {"ok": True, "message": f"{name} connected on port {target_port}."}
    except OSError as exc:
        return {"ok": False, "message": f"{name} could not connect. {exc}"}


@router.post("/trunks/{name}/disable")
def disable_trunk_from_ui(
    name: str,
    connection: psycopg.Connection = Depends(get_connection),
) -> RedirectResponse:
    updated = update_trunk_enabled(connection, name, False)
    if updated:
        reload_result = sync_asterisk_config(connection)
        params = urlencode({"result": "success", "detail": f"Disabled trunk {name}. Asterisk reload status: {reload_result['status']}."})
    else:
        params = urlencode({"result": "error", "detail": f"Trunk {name} was not found."})
    return RedirectResponse(url=f"/trunks?{params}", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/trunks/{name}/delete")
def delete_trunk_from_ui(
    name: str,
    connection: psycopg.Connection = Depends(get_connection),
) -> RedirectResponse:
    deleted = delete_trunk(connection, name)
    if deleted:
        reload_result = sync_asterisk_config(connection)
        params = urlencode(
            {
                "result": "success",
                "detail": (
                    f"Deleted trunk {name}. "
                    f"Asterisk reload status: {reload_result['status']}."
                ),
            }
        )
    else:
        params = urlencode({"result": "error", "detail": f"Trunk {name} was not found."})
    return RedirectResponse(url=f"/trunks?{params}", status_code=status.HTTP_303_SEE_OTHER)


def _normalize_protocol(protocol: str) -> str:
    protocol_value = (protocol or "auto").strip().lower()
    if protocol_value not in PROTOCOL_TO_TRANSPORT:
        return "auto"
    return protocol_value


def _host_with_port(host: str, port: str, protocol: str) -> str:
    clean_host = host.strip().removeprefix("sip:").removeprefix("sips:")
    if ":" in clean_host.rsplit("@", 1)[-1]:
        return clean_host
    port_value = int(port) if port.strip().isdigit() else DEFAULT_PORTS[protocol]
    return f"{clean_host}:{port_value}"


def _split_host_port(host: str, protocol: str) -> tuple[str, int]:
    clean_host = host.strip().removeprefix("sip:").removeprefix("sips:")
    if ":" in clean_host.rsplit("@", 1)[-1]:
        host_part, port_part = clean_host.rsplit(":", 1)
        return host_part, int(port_part) if port_part.isdigit() else DEFAULT_PORTS[protocol]
    return clean_host, DEFAULT_PORTS[protocol]


def _protocol_from_transport(transport: str) -> str:
    for protocol, transport_name in PROTOCOL_TO_TRANSPORT.items():
        if transport_name == transport and protocol != "auto":
            return protocol
    return "auto"
