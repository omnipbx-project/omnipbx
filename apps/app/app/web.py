from fastapi import Request
from starlette.templating import Jinja2Templates

from app.core.settings import get_settings
from app.services.updates import get_update_banner


templates = Jinja2Templates(directory="app/templates")

NAV_SECTIONS = [
    {
        "title": "Main",
        "items": [
            {"href": "/dashboard", "label": "Dashboard", "icon": "📊"},
            {"href": "/extensions", "label": "Users", "icon": "👥"},
            {"href": "/trunks", "label": "Trunks", "icon": "🌐"},
            {"href": "/inbound-routes", "label": "Call Flow", "icon": "↗"},
            {"href": "/call-logs", "label": "Calls", "icon": "☎"},
            {"href": "/welcome-messages", "label": "Voicemail", "icon": "✉"},
            {"href": "/callbacks", "label": "Contacts", "icon": "◎"},
            {"href": "/audit-log", "label": "Reports", "icon": "▣"},
            {"href": "/setup", "label": "Settings", "icon": "⚙"},
            {"href": "/status", "label": "Advanced", "icon": "◇"},
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
