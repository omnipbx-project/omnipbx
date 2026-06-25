from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
import psycopg

from app.core.db import get_connection
from app.services.call_records import list_call_records
from app.services.date_ranges import date_range_context, resolve_date_range
from app.services.setup import get_system_settings
from app.web import render_template


router = APIRouter(tags=["call-records"])


@router.get("/call-records", response_class=HTMLResponse)
def call_records_page(
    request: Request,
    search: str = "",
    direction: str = "all",
    user: str = "all",
    range: str = "7d",
    date_from: str = "",
    date_to: str = "",
    limit: int = 200,
    connection: psycopg.Connection = Depends(get_connection),
) -> HTMLResponse:
    timezone_name = str(get_system_settings(connection).get("timezone") or "UTC")
    resolved_range = resolve_date_range(range, date_from=date_from, date_to=date_to, default="7d", timezone_name=timezone_name)
    report = list_call_records(
        connection,
        search=search,
        direction=direction,
        user=user,
        date_from=resolved_range.date_from or None,
        date_to=resolved_range.date_to or None,
        timezone_name=timezone_name,
        limit=limit,
    )
    return render_template(
        request,
        "call_records/index.html",
        page_title="Call Records",
        page_description="Recorded calls with simple filters for date, direction, and user.",
        active_nav="/call-records",
        rows=report["rows"],
        summary=report["summary"],
        users=report["users"],
        search=search,
        direction=direction,
        user=user,
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
    )
