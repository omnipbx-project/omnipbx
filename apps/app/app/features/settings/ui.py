from __future__ import annotations

from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
import psycopg

from app.core.db import get_connection
from app.core.settings import get_settings
from app.services.admin_accounts import get_smtp_settings, list_admin_accounts
from app.services.backup import list_backup_files
from app.services.setup import get_system_settings, save_company_network_settings, save_timezone_setting
from app.services.system_tools import list_security_rules
from app.services.updates import get_update_overview
from app.web import render_template


router = APIRouter(tags=["settings"])


@router.get("/settings", response_class=HTMLResponse)
def settings_page(
    request: Request,
    connection: psycopg.Connection = Depends(get_connection),
) -> HTMLResponse:
    system_settings = get_system_settings(connection)
    smtp_settings = get_smtp_settings(connection)
    result = request.query_params.get("result", "")
    detail = request.query_params.get("detail", "")
    return render_template(
        request,
        "settings/index.html",
        page_title="Settings",
        page_description="Safe business settings for owners and admins.",
        active_nav="/settings",
        result=result,
        detail=detail,
        system_settings=system_settings,
        countries=_country_options(),
        languages=_language_options(),
        deployment_modes=_deployment_mode_options(),
        access_modes=_access_mode_options(),
        timezone_options=_timezone_options(str(system_settings.get("timezone") or "UTC")),
        smtp_settings=smtp_settings,
        update_overview=get_update_overview(get_settings()),
        admins=list_admin_accounts(connection),
        backups=list_backup_files(),
        security_rules=list_security_rules(connection),
        page_js=["/static/js/updates.js", "/static/js/settings.js"],
    )


@router.post("/settings/timezone")
def save_timezone_from_settings(
    timezone: str = Form(...),
    connection: psycopg.Connection = Depends(get_connection),
) -> RedirectResponse:
    try:
        save_timezone_setting(connection, timezone)
        params = urlencode({"result": "success", "detail": "Timezone saved."})
    except ValueError as exc:
        params = urlencode({"result": "error", "detail": str(exc)})
    return RedirectResponse(url=f"/settings?{params}", status_code=303)


@router.post("/settings/company-network")
def save_company_network_from_settings(
    company_name: str = Form(...),
    country: str = Form(default="Bangladesh"),
    timezone: str = Form(...),
    default_language: str = Form(default="en"),
    dialing_region: str = Form(default="+880"),
    deployment_mode: str = Form(default="office"),
    access_mode: str = Form(default="local_network"),
    behind_nat_raw: str | None = Form(default=None),
    external_host: str = Form(default=""),
    sip_port: int = Form(default=5060),
    rtp_start: int = Form(default=10000),
    rtp_end: int = Form(default=20000),
    local_networks: str = Form(default=""),
    connection: psycopg.Connection = Depends(get_connection),
) -> RedirectResponse:
    try:
        save_company_network_settings(
            connection,
            company_name=company_name,
            country=country,
            timezone_name=timezone,
            default_language=default_language,
            dialing_region=dialing_region,
            deployment_mode=deployment_mode,
            access_mode=access_mode,
            behind_nat=behind_nat_raw is not None,
            external_host=external_host,
            sip_port=sip_port,
            rtp_start=rtp_start,
            rtp_end=rtp_end,
            local_networks=local_networks,
        )
        params = urlencode({"result": "success", "detail": "Company and network settings saved."})
    except ValueError as exc:
        params = urlencode({"result": "error", "detail": str(exc)})
    return RedirectResponse(url=f"/settings?{params}#company-network", status_code=303)


def _country_options() -> list[dict[str, str]]:
    return [
        {"value": "Bangladesh", "label": "Bangladesh"},
        {"value": "United States", "label": "United States"},
        {"value": "United Kingdom", "label": "United Kingdom"},
        {"value": "United Arab Emirates", "label": "United Arab Emirates"},
        {"value": "India", "label": "India"},
    ]


def _language_options() -> list[dict[str, str]]:
    return [
        {"value": "en", "label": "English"},
        {"value": "bn", "label": "Bangla"},
        {"value": "ar", "label": "Arabic"},
        {"value": "hi", "label": "Hindi"},
    ]


def _deployment_mode_options() -> list[dict[str, str]]:
    return [
        {"value": "office", "label": "Office or Home PBX"},
        {"value": "public_server", "label": "Public Internet or Cloud"},
        {"value": "advanced", "label": "Advanced Network"},
    ]


def _access_mode_options() -> list[dict[str, str]]:
    return [
        {"value": "local_network", "label": "Private Office Network"},
        {"value": "public_domain", "label": "Public Domain"},
        {"value": "public_ip", "label": "Public IP"},
        {"value": "private_self_hosted", "label": "Bring Your Own Certificate"},
        {"value": "http_only", "label": "HTTP Only"},
    ]


def _timezone_options(current_timezone: str) -> list[dict[str, str]]:
    options = [
        {"value": "UTC", "label": "UTC"},
        {"value": "Asia/Dhaka", "label": "Bangladesh - Asia/Dhaka"},
        {"value": "Asia/Kolkata", "label": "India - Asia/Kolkata"},
        {"value": "Asia/Dubai", "label": "UAE - Asia/Dubai"},
        {"value": "Asia/Singapore", "label": "Singapore - Asia/Singapore"},
        {"value": "Europe/London", "label": "UK - Europe/London"},
        {"value": "America/New_York", "label": "US Eastern - America/New_York"},
        {"value": "America/Chicago", "label": "US Central - America/Chicago"},
        {"value": "America/Denver", "label": "US Mountain - America/Denver"},
        {"value": "America/Los_Angeles", "label": "US Pacific - America/Los_Angeles"},
    ]
    if current_timezone and current_timezone not in {item["value"] for item in options}:
        options.insert(0, {"value": current_timezone, "label": current_timezone})
    return options
