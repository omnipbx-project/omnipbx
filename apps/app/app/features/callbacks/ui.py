from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
import psycopg

from app.core.db import get_connection
from app.services.call_logs import list_callback_worklist, update_callback_followup
from app.web import render_template


router = APIRouter(tags=["callbacks"])


@router.get("/callbacks", response_class=HTMLResponse)
def callbacks_page(
    request: Request,
    search: str = "",
    open_only: bool = True,
    connection: psycopg.Connection = Depends(get_connection),
) -> HTMLResponse:
    report = list_callback_worklist(connection, search=search, open_only=open_only)
    return render_template(
        request,
        "callbacks/index.html",
        page_title="Callbacks",
        page_description="Callback follow-up is separated from call logs, with one worklist for missed and abandoned inbound calls.",
        active_nav="/callbacks",
        rows=report["rows"],
        summary=report["summary"],
        search=search,
        open_only=open_only,
    )


@router.post("/callbacks/{linkedid}/update")
def update_callback_from_ui(
    linkedid: str,
    completed_raw: str | None = Form(default=None),
    callback_number: str = Form(default=""),
    note: str = Form(default=""),
    connection: psycopg.Connection = Depends(get_connection),
) -> RedirectResponse:
    update_callback_followup(
        connection,
        linkedid,
        completed=completed_raw is not None,
        callback_number=callback_number,
        note=note,
    )
    params = urlencode({"search": "", "open_only": "1"})
    return RedirectResponse(url=f"/callbacks?{params}", status_code=303)
