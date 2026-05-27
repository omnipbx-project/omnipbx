from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
import psycopg

from app.core.db import get_connection
from app.features.status.service import collect_status_snapshot
from app.services.extensions import list_extensions
from app.web import render_template

def get_ongoing_calls():
    return []


def get_trunk_status():
    return []


def get_system_metrics():
    return {"cpu": 25, "ram": 45, "disk": 60}


def get_recent_logs():
    return []


def get_recent_call_logs():
    return []


def get_dashboard_notifications(status_snapshot: dict[str, object]) -> list[dict[str, str]]:
    summary = status_snapshot.get("summary", {})
    offline_count = int(summary.get("extensions_offline", 0) or 0)
    unknown_count = int(summary.get("extensions_unknown", 0) or 0)
    notifications = [
        {
            "severity": "danger",
            "title": "Trunk offline",
            "description": "One or more external lines may need attention.",
            "time": "Now",
        },
        {
            "severity": "warning",
            "title": "Update available",
            "description": "A newer OmniPBX release can be installed.",
            "time": "Today",
        },
        {
            "severity": "success",
            "title": "Backup completed",
            "description": "Latest scheduled backup finished successfully.",
            "time": "2h ago",
        },
    ]
    if offline_count:
        notifications.insert(
            0,
            {
                "severity": "danger",
                "title": "Users offline",
                "description": f"{offline_count} registered user{'s' if offline_count != 1 else ''} offline.",
                "time": "Now",
            },
        )
    if unknown_count:
        notifications.append(
            {
                "severity": "warning",
                "title": "Registration unknown",
                "description": f"{unknown_count} user{'s' if unknown_count != 1 else ''} need presence verification.",
                "time": "Now",
            }
        )
    return notifications[:6]

router = APIRouter(tags=["dashboard"])


@router.get("/dashboard", response_class=HTMLResponse)
def dashboard_page(
    request: Request,
    connection: psycopg.Connection = Depends(get_connection),
) -> HTMLResponse:
    extensions = list_extensions(connection)
    status_snapshot = collect_status_snapshot(connection)
    extension_statuses = {
        row["extension"]: row["status"] for row in status_snapshot["extensions"]
    }

    return render_template(
        request,
        "dashboard/index.html",
        page_title="Dashboard",
        page_description="",
        active_nav="/dashboard",
        extensions=extensions,
        extension_statuses=extension_statuses,
        status_snapshot=status_snapshot,
        ongoing_calls=get_ongoing_calls(),
        trunks=get_trunk_status(),
        metrics=get_system_metrics(),
        logs=get_recent_logs(),
        recent_call_logs=get_recent_call_logs(),
        dashboard_notifications=get_dashboard_notifications(status_snapshot),
    )
