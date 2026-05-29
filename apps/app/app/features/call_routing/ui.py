from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
import psycopg
from starlette import status

from app.core.db import get_connection
from app.services.asterisk import sync_asterisk_config
from app.services.call_routing import (
    delete_call_routing_rule,
    list_call_routing_item_rules,
    list_call_routing_rules,
    rules_by_item,
    save_call_routing_rule,
)
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

ROUTING_FORMS = {
    ("incoming-calls", "holiday-rules"): [
        {"name": "route", "label": "Incoming route", "placeholder": "Main line"},
        {"name": "date_range", "label": "Holiday dates", "placeholder": "2026-12-24 to 2026-12-26"},
        {"name": "message", "label": "Message or sound", "placeholder": "holiday-closed"},
    ],
    ("incoming-calls", "voicemail"): [
        {"name": "route", "label": "Incoming route", "placeholder": "Main line"},
        {"name": "mailbox", "label": "Mailbox", "placeholder": "1001"},
        {"name": "when", "label": "Send calls when", "placeholder": "No answer"},
    ],
    ("incoming-calls", "blocked-numbers"): [
        {"name": "caller", "label": "Caller number", "placeholder": "+15551234567"},
        {"name": "message", "label": "Message or sound", "placeholder": "ss-noservice"},
    ],
    ("incoming-calls", "failover"): [
        {"name": "route", "label": "Incoming route", "placeholder": "Main line"},
        {"name": "backup_type", "label": "Backup type", "placeholder": "Extension, Ring Group, Queue"},
        {"name": "backup", "label": "Backup destination", "placeholder": "1001"},
    ],
    ("outgoing-calls", "routes"): [
        {"name": "dial_pattern", "label": "Numbers starting with", "placeholder": "9"},
        {"name": "trunk", "label": "Use trunk", "placeholder": "provider-main"},
        {"name": "remove_digits", "label": "Remove first digits", "placeholder": "1"},
    ],
    ("outgoing-calls", "dial-rules"): [
        {"name": "dial_pattern", "label": "User dials", "placeholder": "0"},
        {"name": "replace_with", "label": "Send as", "placeholder": "+880"},
        {"name": "note", "label": "Simple note", "placeholder": "Local mobile numbers"},
    ],
    ("outgoing-calls", "calling-permissions"): [
        {"name": "group", "label": "User group", "placeholder": "Sales"},
        {"name": "allowed", "label": "Allowed calls", "placeholder": "Local, Mobile"},
    ],
    ("internal-calls", "voicemail"): [
        {"name": "extension", "label": "Extension", "placeholder": "1001"},
        {"name": "mailbox", "label": "Mailbox", "placeholder": "1001"},
    ],
    ("internal-calls", "conference-rooms"): [
        {"name": "room", "label": "Room extension", "placeholder": "7001"},
        {"name": "pin", "label": "PIN", "placeholder": "1234"},
    ],
}


@router.get("/call-routing", response_class=HTMLResponse)
def call_routing_page(
    request: Request,
    connection: psycopg.Connection = Depends(get_connection),
) -> HTMLResponse:
    grouped_rules = rules_by_item(list_call_routing_rules(connection))
    sections = _sections_with_counts(grouped_rules)
    return render_template(
        request,
        "call_routing/index.html",
        page_title="Call Routing",
        page_description="",
        active_nav="/call-routing",
        sections=sections,
        topbar_search={
            "placeholder": "Search call type...",
            "label": "Search call type",
        },
        page_css=["/static/css/call_routing.css"],
        page_js=["/static/js/call_routing.js"],
    )


@router.get("/call-routing/{section_slug}", response_class=HTMLResponse)
def call_routing_section_page(
    section_slug: str,
    request: Request,
    connection: psycopg.Connection = Depends(get_connection),
) -> HTMLResponse:
    grouped_rules = rules_by_item(list_call_routing_rules(connection))
    section = _find_section(section_slug, grouped_rules)
    return render_template(
        request,
        "call_routing/section.html",
        page_title=section["title"],
        page_description="",
        active_nav="/call-routing",
        section=section,
        topbar_search={
            "placeholder": "Search routing option...",
            "label": "Search routing option",
        },
        page_css=["/static/css/call_routing.css"],
        page_js=["/static/js/call_routing.js"],
    )


@router.get("/call-routing/{section_slug}/{item_slug}", response_class=HTMLResponse)
def call_routing_detail_page(
    section_slug: str,
    item_slug: str,
    request: Request,
    connection: psycopg.Connection = Depends(get_connection),
) -> HTMLResponse:
    grouped_rules = rules_by_item(list_call_routing_rules(connection))
    section, item = _find_item(section_slug, item_slug, grouped_rules)
    return render_template(
        request,
        "call_routing/detail.html",
        page_title=item["title"],
        page_description="",
        active_nav="/call-routing",
        section=section,
        item=item,
        fields=ROUTING_FORMS.get((section_slug, item_slug), []),
        rules=list_call_routing_item_rules(connection, section_slug, item_slug),
        result=request.query_params.get("result", ""),
        detail=request.query_params.get("detail", ""),
        topbar_search=None,
        page_css=["/static/css/call_routing.css"],
    )


@router.post("/call-routing/{section_slug}/{item_slug}/save")
async def save_call_routing_detail(
    section_slug: str,
    item_slug: str,
    request: Request,
    name: str = Form(...),
    enabled_raw: str | None = Form(default=None),
    connection: psycopg.Connection = Depends(get_connection),
) -> RedirectResponse:
    fields = ROUTING_FORMS.get((section_slug, item_slug), [])
    form = await request.form()
    config = {field["name"]: str(form.get(field["name"], "")) for field in fields}
    try:
        save_call_routing_rule(
            connection,
            section_slug=section_slug,
            item_slug=item_slug,
            name=name,
            enabled=enabled_raw is not None,
            config=config,
        )
        reload_result = sync_asterisk_config(connection)
        params = urlencode(
            {
                "result": "success",
                "detail": f"Saved {name.strip()}. Asterisk reload status: {reload_result['status']}.",
            }
        )
    except Exception as exc:
        params = urlencode({"result": "error", "detail": str(exc)})
    return RedirectResponse(
        url=f"/call-routing/{section_slug}/{item_slug}?{params}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/call-routing/{section_slug}/{item_slug}/{rule_id}/delete")
def delete_call_routing_detail(
    section_slug: str,
    item_slug: str,
    rule_id: int,
    connection: psycopg.Connection = Depends(get_connection),
) -> RedirectResponse:
    deleted = delete_call_routing_rule(connection, rule_id)
    reload_result = sync_asterisk_config(connection)
    params = urlencode(
        {
            "result": "success" if deleted else "error",
            "detail": (
                f"Deleted rule. Asterisk reload status: {reload_result['status']}."
                if deleted
                else "Rule was not found."
            ),
        }
    )
    return RedirectResponse(
        url=f"/call-routing/{section_slug}/{item_slug}?{params}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


def _sections_with_counts(grouped_rules: dict[tuple[str, str], list[dict]]) -> list[dict[str, object]]:
    sections = _sections_with_links()
    for section in sections:
        section_rule_count = 0
        for item in section["items"]:
            rules = grouped_rules.get((section["slug"], item["slug"]), [])
            if rules:
                section_rule_count += len(rules)
                item["status"] = f"{len(rules)} saved"
        section["href"] = f"/call-routing/{section['slug']}"
        section["saved_count"] = section_rule_count
        section["status"] = f"{section_rule_count} saved" if section_rule_count else "Open"
    return sections


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


def _find_item(
    section_slug: str,
    item_slug: str,
    grouped_rules: dict[tuple[str, str], list[dict]] | None = None,
) -> tuple[dict[str, object], dict[str, str]]:
    for section in _sections_with_counts(grouped_rules or {}):
        if section["slug"] != section_slug:
            continue
        for item in section["items"]:
            if item["slug"] == item_slug:
                return section, item
    fallback_section = CALL_ROUTING_SECTIONS[0]
    fallback_item = fallback_section["items"][0]
    return fallback_section, fallback_item


def _find_section(
    section_slug: str,
    grouped_rules: dict[tuple[str, str], list[dict]] | None = None,
) -> dict[str, object]:
    grouped_rules = grouped_rules or {}
    for section in _sections_with_counts(grouped_rules):
        if section["slug"] == section_slug:
            return section
    return _sections_with_counts(grouped_rules)[0]
