from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
import psycopg

from app.core.db import get_connection
from app.services.audit import list_admin_audit_entries
from app.services.admin_accounts import role_can_manage_admins
from app.web import render_template


router = APIRouter(tags=["audit-log"])


@router.get("/audit-log", response_class=HTMLResponse)
def audit_log_page(
    request: Request,
    connection: psycopg.Connection = Depends(get_connection),
) -> HTMLResponse:
    current_user = request.state.current_user
    entries = list_admin_audit_entries(connection, limit=200)
    return render_template(
        request,
        "audit_log/index.html",
        page_title="Audit Log",
        page_description="Review admin actions, password recovery events, SMTP changes, and backups from one place.",
        active_nav="/audit-log",
        entries=entries,
        can_manage=bool(current_user and role_can_manage_admins(current_user.get("role"))),
    )
