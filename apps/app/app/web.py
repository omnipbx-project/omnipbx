from fastapi import Request
from starlette.templating import Jinja2Templates

from app.core.settings import get_settings
from app.services.updates import get_update_banner


templates = Jinja2Templates(directory="app/templates")

NAV_SECTIONS = [
    {
        "title": "Overview",
        "items": [
            {"href": "/dashboard", "label": "Dashboard", "icon": "📊"},
            {"href": "/status", "label": "Live Status", "icon": "🟢"},
            {"href": "/call-logs", "label": "Call Logs", "icon": "📜"},
            {"href": "/callbacks", "label": "Callbacks", "icon": "🤙"},
        ],
    },
    {
        "title": "Users & Access",
        "items": [
            {"href": "/admin-accounts", "label": "Admin Accounts", "icon": "👤"},
            {"href": "/extensions", "label": "Extensions", "icon": "📞"},
            {"href": "/softphone", "label": "Softphone", "icon": "💻"},
            {"href": "/setup", "label": "Setup Wizard", "icon": "🪄"},
        ],
    },
    {
        "title": "Routing",
        "items": [
            {"href": "/trunks", "label": "Trunks", "icon": "🌐"},
            {"href": "/inbound-routes", "label": "Inbound", "icon": "📥"},
            {"href": "/ring-groups", "label": "Ring Groups", "icon": "👥"},
            {"href": "/queues", "label": "Queues", "icon": "⏳"},
            {"href": "/ivrs", "label": "IVR Menus", "icon": "🤖"},
            {"href": "/working-hours", "label": "Working Hours", "icon": "🕒"},
            {"href": "/welcome-messages", "label": "Welcome", "icon": "👋"},
        ],
    },
    {
        "title": "Platform",
        "items": [
            {"href": "/api-push", "label": "API Push", "icon": "🚀"},
            {"href": "/audit-log", "label": "Audit Log", "icon": "🔍"},
            {"href": "/backup-restore", "label": "Backup", "icon": "💾"},
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
