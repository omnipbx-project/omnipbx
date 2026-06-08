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
            {"href": "/live-overview", "label": "Live Overview", "icon": "◉"},
            {"href": "/extensions", "label": "Users", "icon": "👥"},
            {"href": "/trunks", "label": "Trunks", "icon": "🌐"},
            {"href": "/call-routing", "label": "Call Routing", "icon": "↗"},
            {"href": "/call-logs", "label": "Call Log", "icon": "☎"},
            {"href": "/callbacks", "label": "Follow Up", "icon": "◎"},
            {"href": "/call-records", "label": "Call Records", "icon": "◌"},
            {"href": "/welcome-messages", "label": "Voicemail", "icon": "✉"},
            {"href": "/reports", "label": "Reports", "icon": "▣"},
            {"href": "/settings", "label": "Settings", "icon": "⚙"},
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
    search_by_nav = {
        "/dashboard": {
            "placeholder": "Search user, extension, call...",
            "label": "Search user, extension, call",
        },
        "/live-overview": {
            "placeholder": "Search call, user, trunk...",
            "label": "Search call, user, trunk",
        },
        "/extensions": {
            "placeholder": "Search user or extension...",
            "label": "Search user or extension",
        },
        "/trunks": {
            "placeholder": "Search trunk or provider...",
            "label": "Search trunk or provider",
        },
        "/call-routing": {
            "placeholder": "Search routing option...",
            "label": "Search routing option",
        },
        "/call-logs": {
            "placeholder": "Search caller, number...",
            "label": "Search call log",
        },
        "/callbacks": {
            "placeholder": "Search customer...",
            "label": "Search follow up",
        },
        "/call-records": {
            "placeholder": "Search recording...",
            "label": "Search call records",
        },
        "/welcome-messages": {
            "placeholder": "Search voicemail...",
            "label": "Search voicemail",
        },
        "/audit-log": {
            "placeholder": "Search report...",
            "label": "Search reports",
        },
        "/reports": {
            "placeholder": "Search report...",
            "label": "Search reports",
        },
        "/settings": {
            "placeholder": "Search settings...",
            "label": "Search settings",
        },
        "/status": {
            "placeholder": "Search status...",
            "label": "Search status",
        },
    }
    topbar_search = context.pop(
        "topbar_search",
        search_by_nav.get(
            active_nav,
            {
                "placeholder": "Search this page...",
                "label": "Search this page",
            },
        ),
    )
    show_shell = context.pop("show_shell", True)
    show_header_controls = bool(show_shell and current_user)
    show_notifications = context.pop("show_notifications", show_header_controls)
    show_profile_avatar = context.pop("show_profile_avatar", show_header_controls)
    topbar_action = context.pop("topbar_action", None)
    base_context = {
        "request": request,
        "app_name": settings.app_name,
        "app_version": settings.app_version,
        "page_title": page_title,
        "page_description": page_description,
        "active_nav": active_nav,
        "nav_sections": NAV_SECTIONS,
        "show_shell": show_shell,
        "current_user": current_user,
        "update_banner": get_update_banner(settings),
        "topbar_search": topbar_search,
        "show_notifications": show_notifications,
        "show_profile_avatar": show_profile_avatar,
        "topbar_action": topbar_action,
        "page_css": context.pop("page_css", []),
        "page_js": context.pop("page_js", []),
    }
    base_context.update(context)
    return templates.TemplateResponse(template_name, base_context)
