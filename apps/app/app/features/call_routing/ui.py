from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from app.web import render_template


router = APIRouter(tags=["call-routing"])


CALL_ROUTING_SECTIONS = [
    {
        "slug": "incoming-calls",
        "title": "Incoming Calls",
        "summary": "Choose what happens when customers call your numbers.",
        "items": [
            {
                "slug": "routes",
                "title": "Routes",
                "description": "Send each phone number to the right team, greeting, menu, or user.",
                "href": "/inbound-routes",
                "status": "Ready",
            },
            {
                "slug": "welcome-greeting",
                "title": "Welcome Greeting",
                "description": "Play a greeting before the call reaches a person or menu.",
                "href": "/welcome-messages",
                "status": "Ready",
            },
            {
                "slug": "office-hours",
                "title": "Office Hours",
                "description": "Use different call handling for open and closed hours.",
                "href": "/working-hours",
                "status": "Ready",
            },
            {
                "slug": "holiday-rules",
                "title": "Holiday Rules",
                "description": "Handle holidays and special closed days without changing normal hours.",
                "status": "Planned",
            },
            {
                "slug": "ivr",
                "title": "IVR",
                "description": "Let callers press a number to choose sales, support, or another destination.",
                "href": "/ivrs",
                "status": "Ready",
            },
            {
                "slug": "call-queues",
                "title": "Call Queues",
                "description": "Keep callers waiting for the next available team member.",
                "href": "/queues",
                "status": "Ready",
            },
            {
                "slug": "ring-groups",
                "title": "Ring Groups",
                "description": "Ring several users together until someone answers.",
                "href": "/ring-groups",
                "status": "Ready",
            },
            {
                "slug": "voicemail",
                "title": "Voicemail",
                "description": "Send missed calls to a mailbox when nobody can answer.",
                "status": "Planned",
            },
            {
                "slug": "blocked-numbers",
                "title": "Blocked Numbers",
                "description": "Stop unwanted callers before they reach your team.",
                "status": "Planned",
            },
            {
                "slug": "failover",
                "title": "Failover",
                "description": "Choose a backup destination if the first choice is unavailable.",
                "status": "Planned",
            },
        ],
    },
    {
        "slug": "outgoing-calls",
        "title": "Outgoing Calls",
        "summary": "Control how your team places calls to outside numbers.",
        "items": [
            {
                "slug": "routes",
                "title": "Routes",
                "description": "Choose which outside line is used for outgoing calls.",
                "status": "Planned",
            },
            {
                "slug": "dial-rules",
                "title": "Dial Rules",
                "description": "Make dialing simple with rules for local, mobile, and international numbers.",
                "status": "Planned",
            },
            {
                "slug": "trunk-priority",
                "title": "Trunk Priority",
                "description": "Pick the first, second, and backup provider for outgoing calls.",
                "href": "/trunks",
                "status": "Basic setup",
            },
            {
                "slug": "calling-permissions",
                "title": "Calling Permissions",
                "description": "Limit who can call local, mobile, national, or international numbers.",
                "status": "Planned",
            },
        ],
    },
    {
        "slug": "internal-calls",
        "title": "Internal Calls",
        "summary": "Manage calls between users and shared internal destinations.",
        "items": [
            {
                "slug": "extension-calls",
                "title": "Extension Calls",
                "description": "Let users call each other by extension.",
                "href": "/extensions",
                "status": "Ready",
            },
            {
                "slug": "ring-groups",
                "title": "Ring Groups",
                "description": "Create shared team extensions such as Sales or Support.",
                "href": "/ring-groups",
                "status": "Ready",
            },
            {
                "slug": "voicemail",
                "title": "Voicemail",
                "description": "Manage internal voicemail behavior for missed calls.",
                "status": "Planned",
            },
            {
                "slug": "conference-rooms",
                "title": "Conference Rooms",
                "description": "Create meeting rooms that users can dial into.",
                "status": "Planned",
            },
        ],
    },
]


@router.get("/call-routing", response_class=HTMLResponse)
def call_routing_page(request: Request) -> HTMLResponse:
    return render_template(
        request,
        "call_routing/index.html",
        page_title="Call Routing",
        page_description="",
        active_nav="/call-routing",
        sections=_sections_with_links(),
        topbar_search={
            "placeholder": "Search routing option...",
            "label": "Search routing option",
        },
        page_css=["/static/css/call_routing.css"],
        page_js=["/static/js/call_routing.js"],
    )


@router.get("/call-routing/{section_slug}/{item_slug}", response_class=HTMLResponse)
def call_routing_detail_page(section_slug: str, item_slug: str, request: Request) -> HTMLResponse:
    section, item = _find_item(section_slug, item_slug)
    return render_template(
        request,
        "call_routing/detail.html",
        page_title=item["title"],
        page_description="",
        active_nav="/call-routing",
        section=section,
        item=item,
        topbar_search=None,
        page_css=["/static/css/call_routing.css"],
    )


def _sections_with_links() -> list[dict[str, object]]:
    sections: list[dict[str, object]] = []
    for section in CALL_ROUTING_SECTIONS:
        items = []
        for item in section["items"]:
            linked_item = dict(item)
            linked_item["href"] = item.get("href") or f"/call-routing/{section['slug']}/{item['slug']}"
            items.append(linked_item)
        sections.append({**section, "items": items})
    return sections


def _find_item(section_slug: str, item_slug: str) -> tuple[dict[str, object], dict[str, str]]:
    for section in _sections_with_links():
        if section["slug"] != section_slug:
            continue
        for item in section["items"]:
            if item["slug"] == item_slug:
                return section, item
    fallback_section = CALL_ROUTING_SECTIONS[0]
    fallback_item = fallback_section["items"][0]
    return fallback_section, fallback_item
