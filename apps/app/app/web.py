from fastapi import Request
from starlette.templating import Jinja2Templates

from app.core.settings import get_settings
from app.services.updates import get_update_banner


templates = Jinja2Templates(directory="app/templates")

NAV_SECTIONS = [
    {
        "title": "Overview",
        "items": [
            {"href": "/dashboard", "label": "Dashboard", "icon": "DB"},
            {"href": "/status", "label": "Live Status", "icon": "LS"},
            {"href": "/call-logs", "label": "Call Logs", "icon": "CL"},
            {"href": "/callbacks", "label": "Callbacks", "icon": "CB"},
        ],
    },
    {
        "title": "Users & Access",
        "items": [
            {"href": "/admin-accounts", "label": "Admin Accounts", "icon": "AA"},
            {"href": "/extensions", "label": "Extensions", "icon": "EX"},
            {"href": "/softphone", "label": "Softphone", "icon": "SP"},
            {"href": "/setup", "label": "Setup", "icon": "ST"},
        ],
    },
    {
        "title": "Routing",
        "items": [
            {"href": "/trunks", "label": "Trunks", "icon": "TR"},
            {"href": "/inbound-routes", "label": "Inbound", "icon": "IN"},
            {"href": "/ring-groups", "label": "Ring Groups", "icon": "RG"},
            {"href": "/queues", "label": "Queues", "icon": "QU"},
            {"href": "/ivrs", "label": "IVR", "icon": "IV"},
            {"href": "/working-hours", "label": "Working Hours", "icon": "WH"},
            {"href": "/welcome-messages", "label": "Welcome", "icon": "WM"},
        ],
    },
    {
        "title": "Platform",
        "items": [
            {"href": "/api-push", "label": "API Push", "icon": "AP"},
            {"href": "/audit-log", "label": "Audit Log", "icon": "AL"},
            {"href": "/backup-restore", "label": "Backup & Restore", "icon": "BR"},
        ],
    },
]


def render_template(
    request: Request,
    template_name: str,
    *,
    page_title: str,
    page_description: str,
    active_nav: str,
    **context,
):
    settings = get_settings()
    current_user = getattr(request.state, "current_user", None)
    base_context = {
        "request": request,
        "app_name": settings.app_name,
        "app_version": settings.app_version,
        "page_title": page_title,
        "page_description": page_description,
        "active_nav": active_nav,
        "nav_sections": NAV_SECTIONS,
        "show_shell": context.pop("show_shell", True),
        "current_user": current_user,
        "update_banner": get_update_banner(settings),
    }
    base_context.update(context)
    return templates.TemplateResponse(template_name, base_context)
