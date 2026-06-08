from urllib.parse import urlencode
from io import StringIO
import csv

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
import psycopg

from app.core.db import get_connection
from app.services.call_logs import list_call_logs, sync_cdr_from_asterisk
from app.services.date_ranges import date_range_context, resolve_date_range
from app.services.setup import get_system_settings
from app.web import render_template


router = APIRouter(tags=["call-logs"])


@router.get("/call-logs", response_class=HTMLResponse)
def call_logs_page(
    request: Request,
    search: str = "",
    category: str = "all",
    direction: str = "all",
    range: str = "7d",
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int = 100,
    connection: psycopg.Connection = Depends(get_connection),
) -> HTMLResponse:
    sync_result = sync_cdr_from_asterisk(connection)
    timezone_name = str(get_system_settings(connection).get("timezone") or "UTC")
    resolved_range = resolve_date_range(range, date_from=date_from or "", date_to=date_to or "", default="7d", timezone_name=timezone_name)
    report = list_call_logs(
        connection,
        search=search,
        direction=direction,
        category=category,
        date_from=resolved_range.date_from,
        date_to=resolved_range.date_to,
        timezone_name=timezone_name,
        limit=limit,
    )
    return render_template(
        request,
        "call_logs/index.html",
        page_title="Call Log",
        page_description="A simple 3CX-style call log for all, missed, abandoned, incoming, and outgoing calls.",
        active_nav="/call-logs",
        rows=report["rows"],
        summary=report["summary"],
        categories=report["categories"],
        category=report["category"],
        search=search,
        direction=direction,
        range=resolved_range.key,
        date_from=resolved_range.date_from,
        date_to=resolved_range.date_to,
        date_range=date_range_context(
            resolved_range.key,
            date_from=resolved_range.date_from,
            date_to=resolved_range.date_to,
            default="7d",
            timezone_name=timezone_name,
        ),
        limit=limit,
        sync_result=sync_result,
    )


@router.post("/call-logs/sync")
def sync_call_logs_from_ui(
    connection: psycopg.Connection = Depends(get_connection),
) -> RedirectResponse:
    result = sync_cdr_from_asterisk(connection)
    params = urlencode({"search": "", "category": "all", "direction": "all", "range": "7d", "limit": 100})
    params = f"{params}&synced={result['imported']}&updated={result['updated']}"
    return RedirectResponse(url=f"/call-logs?{params}", status_code=303)


@router.get("/call-logs/export")
def export_call_logs(
    search: str = "",
    category: str = "all",
    direction: str = "all",
    range: str = "7d",
    date_from: str | None = None,
    date_to: str | None = None,
    connection: psycopg.Connection = Depends(get_connection),
) -> Response:
    timezone_name = str(get_system_settings(connection).get("timezone") or "UTC")
    resolved_range = resolve_date_range(range, date_from=date_from or "", date_to=date_to or "", default="7d", timezone_name=timezone_name)
    report = list_call_logs(
        connection,
        search=search,
        direction=direction,
        category=category,
        date_from=resolved_range.date_from,
        date_to=resolved_range.date_to,
        timezone_name=timezone_name,
        limit=10000,
    )
    handle = StringIO()
    writer = csv.writer(handle)
    writer.writerow(
        [
            "Time",
            "Type",
            "From",
            "To",
            "Direction",
            "Status",
            "Duration",
            "Talk Time",
            "Route",
            "Trunk",
            "Queue",
            "IVR",
            "Linked ID",
            "Recording",
        ]
    )
    for row in report["rows"]:
        writer.writerow(
            [
                row.get("call_time") or "",
                row.get("call_type") or "",
                row.get("caller") or "",
                row.get("callee") or "",
                row.get("direction") or "",
                row.get("disposition") or "",
                row.get("duration") or 0,
                row.get("billsec") or 0,
                row.get("route_name") or "",
                row.get("trunk_name") or "",
                row.get("queue_name") or "",
                row.get("ivr_name") or "",
                row.get("linkedid") or "",
                row.get("recordingfile") or "",
            ]
        )
    return Response(
        handle.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="omnipbx-call-logs.csv"'},
    )
