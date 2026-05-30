from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
import psycopg

from app.core.db import get_connection
from app.services.call_records import list_call_records
from app.web import render_template


router = APIRouter(tags=["call-records"])


@router.get("/call-records", response_class=HTMLResponse)
def call_records_page(
    request: Request,
    search: str = "",
    direction: str = "all",
    user: str = "all",
    date_from: str = "",
    date_to: str = "",
    limit: int = 200,
    connection: psycopg.Connection = Depends(get_connection),
) -> HTMLResponse:
    report = list_call_records(
        connection,
        search=search,
        direction=direction,
        user=user,
        date_from=date_from or None,
        date_to=date_to or None,
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
        date_from=date_from,
        date_to=date_to,
        limit=limit,
    )
