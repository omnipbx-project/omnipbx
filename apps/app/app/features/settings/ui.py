from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
import psycopg

from app.core.db import get_connection
from app.core.settings import get_settings
from app.services.admin_accounts import get_smtp_settings, list_admin_accounts
from app.services.backup import list_backup_files
from app.services.setup import get_system_settings
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
    return render_template(
        request,
        "settings/index.html",
        page_title="Settings",
        page_description="Safe business settings for owners and admins.",
        active_nav="/settings",
        system_settings=system_settings,
        smtp_settings=smtp_settings,
        update_overview=get_update_overview(get_settings()),
        admins=list_admin_accounts(connection),
        backups=list_backup_files(),
        security_rules=list_security_rules(connection),
        page_js=["/static/js/updates.js"],
    )
