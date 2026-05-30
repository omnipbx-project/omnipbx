from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
import psycopg

from app.core.db import get_connection
from app.services.call_logs import list_call_logs, sync_cdr_from_asterisk
from app.web import render_template


router = APIRouter(tags=["call-logs"])


@router.get("/call-logs", response_class=HTMLResponse)
def call_logs_page(
    request: Request,
    search: str = "",
    category: str = "all",
    direction: str = "all",
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int = 100,
    connection: psycopg.Connection = Depends(get_connection),
) -> HTMLResponse:
    sync_result = sync_cdr_from_asterisk(connection)
    report = list_call_logs(
        connection,
        search=search,
        direction=direction,
        category=category,
        date_from=date_from,
        date_to=date_to,
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
        date_from=date_from or "",
        date_to=date_to or "",
        limit=limit,
        sync_result=sync_result,
    )


@router.post("/call-logs/sync")
def sync_call_logs_from_ui(
    connection: psycopg.Connection = Depends(get_connection),
) -> RedirectResponse:
    result = sync_cdr_from_asterisk(connection)
    params = urlencode({"search": "", "category": "all", "direction": "all", "limit": 100})
    params = f"{params}&synced={result['imported']}&updated={result['updated']}"
    return RedirectResponse(url=f"/call-logs?{params}", status_code=303)
