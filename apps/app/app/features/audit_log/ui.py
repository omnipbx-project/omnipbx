from __future__ import annotations

import csv
from io import StringIO

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
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


@router.get("/reports/export")
def export_reports(
    section: str = "overview",
    range: str = "today",
    extension: str = "",
    date_from: str = "",
    date_to: str = "",
    connection: psycopg.Connection = Depends(get_connection),
) -> Response:
    report = build_reports(
        connection,
        section=section,
        range_key=range,
        extension=extension,
        date_from=date_from,
        date_to=date_to,
    )
    handle = StringIO()
    writer = csv.writer(handle)
    _write_report_csv(writer, report)
    filename = f"omnipbx-{report['active_section']}-report.csv"
    return Response(
        handle.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _write_report_csv(writer: csv.writer, report: dict[str, object]) -> None:
    section = str(report.get("active_section") or "overview")
    writer.writerow(["Report", section])
    writer.writerow(["Range", report.get("active_range") or ""])
    writer.writerow(["From", report.get("date_from") or ""])
    writer.writerow(["To", report.get("date_to") or ""])
    writer.writerow([])

    if section in {"overview", "kpi"}:
        writer.writerow(["Metric", "Value"])
        for key, label in (
            ("total", "Total Calls"),
            ("inbound", "Inbound"),
            ("outbound", "Outbound"),
            ("internal", "Internal"),
            ("answered", "Answered"),
            ("missed", "Missed"),
            ("abandoned", "Abandoned"),
            ("answer_rate", "Answer Rate"),
            ("missed_rate", "Missed Rate"),
            ("abandoned_rate", "Abandoned Rate"),
            ("recorded", "Recorded"),
            ("total_talk_time_label", "Total Talk Time"),
            ("avg_talk_time_label", "Average Talk Time"),
        ):
            writer.writerow([label, (report.get("calls") or {}).get(key, "")])
        return

    if section == "calls":
        writer.writerow(["Time", "Caller", "To", "Direction", "Status", "Talk Time"])
        for row in report.get("recent_calls") or []:
            writer.writerow([row.get("call_time"), row.get("caller"), row.get("callee"), row.get("direction"), row.get("simple_status"), row.get("talk_time_label")])
        writer.writerow([])
        writer.writerow(["Daily Trend"])
        writer.writerow(["Date", "Calls", "Inbound", "Outbound", "Answered", "Missed", "Answer Rate", "Talk Time"])
        for row in report.get("daily") or []:
            writer.writerow([row.get("day"), row.get("total_calls"), row.get("inbound"), row.get("outbound"), row.get("answered"), row.get("missed"), row.get("answer_rate"), row.get("talk_time_label")])
        return

    if section == "users":
        writer.writerow(["User", "Extension", "Calls", "Answered", "Talk Time"])
        for row in (report.get("users") or {}).get("top_users") or []:
            writer.writerow([row.get("display_name"), row.get("extension"), row.get("total_calls"), row.get("answered"), row.get("talk_time_label")])
        return

    if section == "queues":
        writer.writerow(["Queue", "Calls", "Answered", "Missed", "Abandoned", "Answer Rate", "SLA Rate", "Average Wait"])
        for row in (report.get("queues") or {}).get("rows") or []:
            writer.writerow([row.get("queue_name"), row.get("total_calls"), row.get("answered"), row.get("missed"), row.get("abandoned"), row.get("answer_rate"), row.get("sla_rate"), row.get("avg_wait_label")])
        return

    if section == "trunks":
        writer.writerow(["Trunk", "Calls", "Inbound", "Outbound", "Answered", "Failed", "Answer Rate", "Failure Rate", "Talk Time", "Last Call"])
        for row in (report.get("trunks") or {}).get("rows") or []:
            writer.writerow([row.get("trunk_name"), row.get("total_calls"), row.get("inbound"), row.get("outbound"), row.get("answered"), row.get("failed"), row.get("answer_rate"), row.get("failure_rate"), row.get("talk_time_label"), row.get("last_call_label")])
        return

    if section == "follow-up":
        writer.writerow(["Customer", "Last Call", "Status", "Assigned To", "Reason"])
        for row in (report.get("follow_up") or {}).get("rows") or []:
            writer.writerow([row.get("callback_number") or row.get("caller_number"), row.get("call_time"), row.get("followup_status"), row.get("assigned_to"), row.get("callback_reason")])
        return

    writer.writerow(["Item", "Value"])
    for row in (report.get("system") or {}).get("health_checks") or []:
        writer.writerow([row.get("label"), row.get("value")])
