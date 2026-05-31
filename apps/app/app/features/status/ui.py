from urllib.parse import urlencode

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
import psycopg

from app.core.db import get_connection
from app.features.status.service import collect_status_snapshot
from app.services.asterisk import sync_asterisk_config
from app.services.setup import custom_certificate_ready, refresh_caddy_config, save_custom_certificate_files, save_ssl_settings
from app.services.system_tools import (
    build_advanced_snapshot,
    collect_system_usage,
    delete_security_rule,
    read_logs,
    run_asterisk_cli,
    run_network_check,
    save_custom_config,
    save_network_settings,
    save_security_rule,
)
from app.services.security import unblock_app_ban
from app.web import render_template


router = APIRouter(tags=["status"])


@router.get("/status", response_class=HTMLResponse)
def status_page(
    request: Request,
    connection: psycopg.Connection = Depends(get_connection),
) -> HTMLResponse:
    return render_template(
        request,
        "status/index.html",
        page_title="Advanced Tools",
        page_description="Technical maintenance tools for system monitor, logs, Asterisk, network, security, and custom config.",
        active_nav="/status",
        snapshot=build_advanced_snapshot(connection),
        result=request.query_params.get("result", ""),
        detail=request.query_params.get("detail", ""),
        page_css=["/static/css/status.css"],
        page_js=["/static/js/status.js"],
    )


@router.get("/status/data")
def status_data(
    connection: psycopg.Connection = Depends(get_connection),
) -> dict[str, object]:
    return collect_status_snapshot(connection)


@router.get("/status/usage")
def status_usage() -> dict[str, object]:
    return {"status": "ok", **collect_system_usage()}


@router.get("/status/logs")
def status_logs(source: str = "asterisk", limit: int = 120, keyword: str = "") -> dict[str, object]:
    return {"status": "ok", **read_logs(source, limit=limit, keyword=keyword)}


@router.post("/status/asterisk-cli")
def status_asterisk_cli(command: str = Form(...)) -> dict[str, object]:
    return {"status": "ok", **run_asterisk_cli(command)}


@router.post("/status/network-check")
def status_network_check(host: str = Form(...), port: str = Form(default="")) -> dict[str, object]:
    parsed_port = int(port) if port.strip().isdigit() else None
    return {"status": "ok", **run_network_check(host, parsed_port)}


@router.post("/status/ssl-settings")
def status_save_ssl_settings(
    access_mode: str = Form(...),
    ssl_mode: str = Form(...),
    external_host: str = Form(default=""),
    ssl_contact_email: str = Form(default=""),
    action: str = Form(default="save"),
    custom_certificate_file: UploadFile | None = File(default=None),
    custom_private_key_file: UploadFile | None = File(default=None),
    connection: psycopg.Connection = Depends(get_connection),
) -> RedirectResponse:
    try:
        if action == "refresh":
            result = refresh_caddy_config(connection)
            url = result.get("public_base_url") or "current address"
            detail = f"SSL config refreshed. Open OmniPBX at {url}."
        else:
            cert_uploaded = _upload_has_file(custom_certificate_file)
            key_uploaded = _upload_has_file(custom_private_key_file)
            if ssl_mode == "custom_certificate":
                if cert_uploaded != key_uploaded:
                    raise ValueError("Upload both the certificate file and the private key file.")
                if cert_uploaded and key_uploaded and custom_certificate_file and custom_private_key_file:
                    save_custom_certificate_files(custom_certificate_file.file, custom_private_key_file.file)
                if not custom_certificate_ready():
                    raise ValueError("Upload the certificate and private key before using custom certificate mode.")
            result = save_ssl_settings(
                connection,
                access_mode=access_mode,
                ssl_mode=ssl_mode,
                external_host=external_host,
                ssl_contact_email=ssl_contact_email,
            )
            url = result.get("public_base_url") or "current address"
            detail = f"SSL settings saved. Caddy will reload automatically. Open OmniPBX at {url}."
        params = urlencode({"result": "success", "detail": detail})
    except ValueError as exc:
        params = urlencode({"result": "error", "detail": str(exc)})
    return RedirectResponse(url=f"/status?{params}", status_code=303)


def _upload_has_file(upload: UploadFile | None) -> bool:
    return bool(upload and upload.filename)


@router.post("/status/security-rules")
def status_save_security_rule(
    rule_type: str = Form(...),
    value: str = Form(...),
    note: str = Form(default=""),
    enabled_raw: str | None = Form(default=None),
    connection: psycopg.Connection = Depends(get_connection),
) -> RedirectResponse:
    try:
        save_security_rule(connection, rule_type=rule_type, value=value, note=note, enabled=enabled_raw is not None)
        sync_asterisk_config(connection)
        params = urlencode({"result": "success", "detail": "Security rule saved."})
    except ValueError as exc:
        params = urlencode({"result": "error", "detail": str(exc)})
    return RedirectResponse(url=f"/status?{params}", status_code=303)


@router.post("/status/security-rules/{rule_id}/delete")
def status_delete_security_rule(
    rule_id: int,
    connection: psycopg.Connection = Depends(get_connection),
) -> RedirectResponse:
    deleted = delete_security_rule(connection, rule_id)
    if deleted:
        sync_asterisk_config(connection)
    params = urlencode({"result": "success" if deleted else "error", "detail": "Security rule deleted." if deleted else "Security rule not found."})
    return RedirectResponse(url=f"/status?{params}", status_code=303)


@router.post("/status/security-bans/{ban_id}/unblock")
def status_unblock_security_ban(
    ban_id: int,
    connection: psycopg.Connection = Depends(get_connection),
) -> RedirectResponse:
    unblocked = unblock_app_ban(connection, ban_id)
    params = urlencode({"result": "success" if unblocked else "error", "detail": "Security ban removed." if unblocked else "Security ban not found."})
    return RedirectResponse(url=f"/status?{params}", status_code=303)


@router.post("/status/custom-config")
def status_save_custom_config(
    config_key: str = Form(...),
    content: str = Form(default=""),
    enabled_raw: str | None = Form(default=None),
    connection: psycopg.Connection = Depends(get_connection),
) -> RedirectResponse:
    try:
        save_custom_config(connection, config_key=config_key, content=content, enabled=enabled_raw is not None)
        reload_result = sync_asterisk_config(connection)
        params = urlencode({"result": "success", "detail": f"Custom config saved. Asterisk reload: {reload_result['status']}."})
    except ValueError as exc:
        params = urlencode({"result": "error", "detail": str(exc)})
    return RedirectResponse(url=f"/status?{params}", status_code=303)


@router.post("/status/network-settings")
def status_save_network_settings(
    trusted_ips: str = Form(default=""),
    blocked_ips: str = Form(default=""),
    open_ports: str = Form(default=""),
    note: str = Form(default=""),
    connection: psycopg.Connection = Depends(get_connection),
) -> RedirectResponse:
    save_network_settings(connection, trusted_ips=trusted_ips, blocked_ips=blocked_ips, open_ports=open_ports, note=note)
    params = urlencode({"result": "success", "detail": "Network notes saved."})
    return RedirectResponse(url=f"/status?{params}", status_code=303)
