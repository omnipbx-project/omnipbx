from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
import psycopg

from app.core.db import get_connection
from app.features.status.service import collect_status_snapshot
from app.web import render_template


router = APIRouter(tags=["status"])


@router.get("/status", response_class=HTMLResponse)
def status_page(
    request: Request,
    connection: psycopg.Connection = Depends(get_connection),
) -> HTMLResponse:
    snapshot = collect_status_snapshot(connection)
    return render_template(
        request,
        "status/index.html",
        page_title="Status",
        page_description="Live SIP endpoint health for OmniPBX. This page replaces the old mixed status UI with a dedicated feature module and template.",
        active_nav="/status",
        snapshot=snapshot,
    )


@router.get("/status/data")
def status_data(
    connection: psycopg.Connection = Depends(get_connection),
) -> dict[str, object]:
    return collect_status_snapshot(connection)
