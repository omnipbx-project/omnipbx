from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
import psycopg

from app.core.db import get_connection
from app.services.admin_accounts import role_can_manage_admins
from app.services.reports import build_reports
from app.web import render_template


router = APIRouter(tags=["audit-log"])


@router.get("/audit-log")
def audit_log_redirect(
    section: str = "overview",
    range: str = "today",
    extension: str = "",
    date_from: str = "",
    date_to: str = "",
) -> RedirectResponse:
    query = f"section={section}&range={range}&extension={extension}&date_from={date_from}&date_to={date_to}"
    return RedirectResponse(url=f"/reports?{query}", status_code=307)


@router.get("/reports", response_class=HTMLResponse)
def reports_page(
    request: Request,
    section: str = "overview",
    range: str = "today",
    extension: str = "",
    date_from: str = "",
    date_to: str = "",
    connection: psycopg.Connection = Depends(get_connection),
) -> HTMLResponse:
    current_user = request.state.current_user
    report = build_reports(
        connection,
        section=section,
        range_key=range,
        extension=extension,
        date_from=date_from,
        date_to=date_to,
    )
    return render_template(
        request,
        "audit_log/index.html",
        page_title="Reports",
        page_description="Simple PBX reports for calls, KPI, follow up, users, queues, and system health.",
        active_nav="/reports",
        report=report,
        can_manage=bool(current_user and role_can_manage_admins(current_user.get("role"))),
    )
