from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
import psycopg

from app.core.db import get_connection
from app.core.settings import get_settings
from app.features.status.service import collect_status_snapshot
from app.services.extensions import list_extensions
from app.services.updates import get_update_overview
from app.web import render_template


router = APIRouter(tags=["dashboard"])


@router.get("/dashboard", response_class=HTMLResponse)
def dashboard_page(
    request: Request,
    connection: psycopg.Connection = Depends(get_connection),
) -> HTMLResponse:
    settings = get_settings()
    extensions = list_extensions(connection)
    status_snapshot = collect_status_snapshot(connection)

    legacy_feature_cards = [
        {
            "title": "Extensions",
            "href": "/extensions",
            "source": "/var/www/html/extensions.py",
            "detail": "Internal endpoints, secrets, and extension-level management.",
        },
        {
            "title": "Status",
            "href": "/status",
            "source": "/var/www/html/status.py",
            "detail": "Live SIP availability and registration visibility.",
        },
        {
            "title": "Trunks",
            "href": "/trunks",
            "source": "/var/www/html/trunk.py",
            "detail": "Provider connectivity, inbound matching, and outbound routes.",
        },
        {
            "title": "Inbound",
            "href": "/inbound-routes",
            "source": "/var/www/html/inbound.py",
            "detail": "Inbound routes, queues, IVRs, prompts, and schedules.",
        },
        {
            "title": "Call Logs",
            "href": "/call-logs",
            "source": "/var/www/html/call_logs.py",
            "detail": "Recordings, callback worklists, and CDR review.",
        },
        {
            "title": "Softphone",
            "href": "/softphone",
            "source": "/var/www/html/soft_phone.py",
            "detail": "Browser softphone, assets, and companion extension delivery.",
        },
    ]

    return render_template(
        request,
        "dashboard/index.html",
        page_title="Dashboard",
        page_description="Modular control surface for OmniPBX. Each feature now lives in its own route, template, and service layer.",
        active_nav="/dashboard",
        extension_count=len(extensions),
        enabled_extension_count=sum(1 for extension in extensions if extension["enabled"]),
        status_summary=status_snapshot["summary"],
        feature_cards=legacy_feature_cards,
        update_overview=get_update_overview(settings),
    )
