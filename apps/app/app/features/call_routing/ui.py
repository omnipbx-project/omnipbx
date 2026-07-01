from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
import psycopg
from starlette import status

from app.core.db import get_connection
from app.services.ami import AmiError, ami_originate_application
from app.services.asterisk import sync_asterisk_config
from app.services.call_routing import (
    delete_call_routing_rule,
    list_call_routing_item_rules,
    list_call_routing_rules,
    rules_by_item,
    save_call_routing_rule,
)
from app.services.extensions import list_extensions
from app.services.trunks import list_trunks
from app.services.user_management import list_groups, profiles_by_extension
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
                "title": "Outbound Rules",
                "description": "Choose who can call out, which trunk they use, and how the dialed number is sent.",
                "status": "Ready",
            },
        ],
    },
    {
        "slug": "internal-calls",
        "title": "Internal Calls",
        "summary": "Manage calls between users and shared internal destinations.",
        "items": [
            {
                "slug": "calling-rules",
                "title": "Calling Rules",
                "description": "Allow groups or individual users to call another group or user. Same-group calls are allowed automatically.",
                "status": "Ready",
            },
            {
                "slug": "voicemail",
                "title": "Voicemail",
                "description": "Send missed, busy, or offline internal calls to the user's mailbox after a timeout.",
                "status": "Ready",
            },
            {
                "slug": "conferences",
                "title": "Conference",
                "description": "Create dial-in conference rooms and save selected users or groups for the meeting.",
                "status": "Ready",
            },
        ],
    },
    {
        "slug": "auto-dialer",
        "title": "Campaign Dialer",
        "summary": "Create calling campaigns, upload contact lists, and let agents work through leads.",
        "href": "/call-routing/auto-dialer/campaigns",
        "items": [
            {
                "slug": "campaigns",
                "title": "Campaigns",
                "description": "Create campaigns, assign callers, upload leads, and choose preview or auto dialing.",
                "href": "/call-routing/auto-dialer/campaigns",
                "status": "Ready",
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
        {"name": "trunk", "label": "Trunk", "type": "trunk_select"},
        {"name": "source_type", "label": "Allowed source", "type": "select", "options": [("group", "Group"), ("user", "User")]},
        {"name": "source_values", "label": "Allowed groups/users", "type": "target_multiselect"},
        {"name": "dial_pattern", "label": "Dial pattern", "placeholder": "_X."},
        {"name": "country_code", "label": "Country code to add", "placeholder": "Optional, for example 880"},
        {"name": "strip_digits", "label": "Remove first digits", "placeholder": "0"},
        {"name": "add_prefix", "label": "Add prefix before sending", "placeholder": "Optional, for example 9 or 0"},
    ],
    ("internal-calls", "calling-rules"): [
        {"name": "source_type", "label": "Source", "type": "select", "options": [("group", "Group"), ("user", "User")]},
        {"name": "source_values", "label": "Source groups/users", "type": "target_multiselect"},
        {"name": "destination_type", "label": "Destination", "type": "select", "options": [("group", "Group"), ("user", "User")]},
        {"name": "destination_values", "label": "Destination groups/users", "type": "target_multiselect"},
    ],
    ("internal-calls", "voicemail"): [
        {"name": "extension", "label": "User", "type": "extension_select"},
        {"name": "mailbox", "label": "Mailbox", "placeholder": "Same as extension when empty"},
        {"name": "timeout", "label": "Ring seconds", "placeholder": "20"},
        {
            "name": "when",
            "label": "Send to voicemail when",
            "type": "select",
            "options": [("no_answer_busy_offline", "No answer, busy, or offline"), ("no_answer", "No answer only"), ("busy_offline", "Busy or offline only")],
        },
    ],
    ("internal-calls", "conferences"): [
        {"name": "room", "label": "Conference extension", "placeholder": "7001"},
        {"name": "pin", "label": "PIN", "placeholder": "Optional"},
        {"name": "mode", "label": "Start mode", "type": "select", "options": [("dial_in", "Dial-in room"), ("immediate", "Immediate call list"), ("scheduled", "Scheduled call list")]},
        {"name": "participant_groups", "label": "Groups", "type": "group_multiselect"},
        {"name": "participant_users", "label": "Users", "type": "extension_multiselect"},
        {"name": "starts_at", "label": "Scheduled time", "placeholder": "2026-06-01 14:30"},
        {"name": "recording", "label": "Recording", "type": "select", "options": [("off", "Off"), ("on", "On")]},
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
    rules = list_call_routing_item_rules(connection, section_slug, item_slug)
    edit_id = request.query_params.get("edit_id", "")
    edit_rule = next((rule for rule in rules if str(rule["id"]) == edit_id), None)
    edit_config_lists = {
        key: [part.strip() for part in str(value).split(",") if part.strip()]
        for key, value in (edit_rule.get("config") if edit_rule else {}).items()
    }
    return render_template(
        request,
        "call_routing/detail.html",
        page_title=item["title"],
        page_description="",
        active_nav="/call-routing",
        section=section,
        item=item,
        fields=ROUTING_FORMS.get((section_slug, item_slug), []),
        rules=rules,
        edit_rule=edit_rule,
        edit_config_lists=edit_config_lists,
        trunks=list_trunks(connection),
        groups=list_groups(connection),
        extensions=list_extensions(connection),
        result=request.query_params.get("result", ""),
        detail=request.query_params.get("detail", ""),
        page_css=["/static/css/call_routing.css"],
        page_js=["/static/js/call_routing.js"],
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
    config = {}
    for field in fields:
        if str(field.get("type", "")).endswith("_multiselect"):
            config[field["name"]] = ", ".join(str(value) for value in form.getlist(field["name"]) if str(value).strip())
        elif field.get("type") == "target_multiselect":
            config[field["name"]] = ", ".join(str(value) for value in form.getlist(field["name"]) if str(value).strip())
        else:
            config[field["name"]] = str(form.get(field["name"], ""))
    try:
        if section_slug == "outgoing-calls" and item_slug == "routes":
            config["dial_pattern"] = config.get("dial_pattern", "").strip() or "_X."
            config["strip_digits"] = config.get("strip_digits", "").strip() or "0"
            if not config.get("trunk", "").strip():
                raise ValueError("Choose a trunk for this outbound rule.")
            if not config.get("source_values", "").strip():
                raise ValueError("Choose at least one allowed user or group.")
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


@router.post("/call-routing/internal-calls/conferences/{rule_id}/start")
def start_conference_now(
    rule_id: int,
    connection: psycopg.Connection = Depends(get_connection),
) -> RedirectResponse:
    rule = next(
        (
            item
            for item in list_call_routing_item_rules(connection, "internal-calls", "conferences")
            if int(item["id"]) == rule_id
        ),
        None,
    )
    if not rule:
        params = urlencode({"result": "error", "detail": "Conference rule was not found."})
        return RedirectResponse(url=f"/call-routing/internal-calls/conferences?{params}", status_code=status.HTTP_303_SEE_OTHER)

    config = rule["config"]
    room = str(config.get("room") or "").strip()
    participants = _conference_participants(connection, config)
    if not room or not participants:
        params = urlencode({"result": "error", "detail": "Choose a room and at least one user or group before starting the conference."})
        return RedirectResponse(url=f"/call-routing/internal-calls/conferences?{params}", status_code=status.HTTP_303_SEE_OTHER)

    called = 0
    errors: list[str] = []
    for extension in participants:
        try:
            ami_originate_application(f"PJSIP/{extension}", "ConfBridge", room)
            called += 1
        except (AmiError, EOFError, OSError, TimeoutError) as exc:
            errors.append(f"{extension}: {exc}")
    if called:
        detail = f"Started conference {room} and called {called} participant{'s' if called != 1 else ''}."
        result = "success"
    else:
        detail = "; ".join(errors[:2]) or "Unable to start conference calls."
        result = "error"
    params = urlencode({"result": result, "detail": detail})
    return RedirectResponse(url=f"/call-routing/internal-calls/conferences?{params}", status_code=status.HTTP_303_SEE_OTHER)


def _sections_with_counts(grouped_rules: dict[tuple[str, str], list[dict]]) -> list[dict[str, object]]:
    sections = _sections_with_links()
    for section in sections:
        section_rule_count = 0
        for item in section["items"]:
            rules = grouped_rules.get((section["slug"], item["slug"]), [])
            if rules:
                section_rule_count += len(rules)
                item["status"] = f"{len(rules)} saved"
        section["href"] = section.get("href") or f"/call-routing/{section['slug']}"
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


def _conference_participants(connection: psycopg.Connection, config: dict) -> list[str]:
    selected_users = {
        value.strip()
        for value in str(config.get("participant_users") or "").split(",")
        if value.strip()
    }
    selected_groups = {
        value.strip()
        for value in str(config.get("participant_groups") or "").split(",")
        if value.strip()
    }
    profiles = profiles_by_extension(connection)
    if selected_groups:
        selected_users.update(
            extension
            for extension, profile in profiles.items()
            if str(profile.get("group_name") or "").strip() in selected_groups
        )
    existing_extensions = {str(row["extension"]) for row in list_extensions(connection)}
    return sorted(extension for extension in selected_users if extension in existing_extensions)
