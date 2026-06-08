from datetime import datetime, UTC
import re
import subprocess

import psycopg

from app.features.status.service import collect_status_snapshot
from app.services.ami import AmiError, ami_command, ami_originate_application
from app.services.extensions import list_extensions
from app.services.trunks import list_trunks
from app.services.user_management import profiles_by_extension


SUPERVISOR_ACTIONS = {
    "listen": {"label": "Listen Quietly", "options": "qbuE"},
    "guide": {"label": "Guide Agent", "options": "qbwuE"},
    "join": {"label": "Join Conversation", "options": "qbBuE"},
}


def collect_live_overview(connection: psycopg.Connection) -> dict[str, object]:
    extensions = list_extensions(connection)
    profiles = profiles_by_extension(connection)
    trunks = list_trunks(connection)
    errors: list[str] = []

    channel_output = _run_asterisk_command("core show channels concise", errors)
    active_calls = _parse_active_calls(channel_output, trunks)
    extensions_on_call = _extensions_on_call(active_calls)

    try:
        status_snapshot = collect_status_snapshot(connection)
    except Exception as exc:
        errors.append(f"User presence unavailable: {exc}")
        status_snapshot = _unknown_status_snapshot(extensions)

    registration_output = _run_asterisk_command("pjsip show registrations", errors)
    trunk_rows = _build_trunk_rows(
        trunks,
        _parse_registration_status(registration_output),
        active_calls,
    )
    active_users = _build_active_users(status_snapshot["extensions"], profiles, extensions_on_call)
    system_status = _system_status(errors, trunk_rows)
    summary = {
        "active_calls": len(active_calls),
        "active_users": len([user for user in active_users if user["status"] in {"Online", "On Call"}]),
        "trunks_online": len([trunk for trunk in trunk_rows if trunk["status"] == "Online"]),
        "system_status": system_status["label"],
    }

    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "summary": summary,
        "active_calls": active_calls,
        "active_users": active_users,
        "trunks": trunk_rows,
        "system_status": system_status,
        "notifications": _notifications(summary, errors, trunk_rows),
    }


def start_supervisor_action(
    connection: psycopg.Connection,
    *,
    supervisor_extension: str,
    channel_id: str,
    action: str,
) -> dict[str, str | bool]:
    supervisor_extension = supervisor_extension.strip()
    channel_id = channel_id.strip()
    action_config = SUPERVISOR_ACTIONS.get(action)

    if not action_config:
        return {"ok": False, "message": "Choose a supported supervisor action."}
    if not re.fullmatch(r"\d{1,8}", supervisor_extension):
        return {"ok": False, "message": "Enter your supervisor extension first."}
    if not re.fullmatch(r"[A-Za-z0-9_./:@;,+-]+", channel_id):
        return {"ok": False, "message": "The selected call is no longer available."}

    overview = collect_live_overview(connection)
    active_channel_ids = {call["id"] for call in overview["active_calls"]}
    if channel_id not in active_channel_ids:
        return {"ok": False, "message": "That call has already ended."}

    app_data = f"{channel_id},{action_config['options']}"
    try:
        ami_originate_application(f"PJSIP/{supervisor_extension}", "ChanSpy", app_data)
    except (AmiError, EOFError, OSError, TimeoutError) as exc:
        command = f"channel originate PJSIP/{supervisor_extension} application ChanSpy {app_data}"
        errors: list[str] = []
        _run_asterisk_command(command, errors)
        if errors:
            return {"ok": False, "message": f"{exc}; {errors[-1]}"}

    return {
        "ok": True,
        "message": f"Calling extension {supervisor_extension} to {action_config['label'].lower()}.",
    }


def _run_asterisk_command(command: str, errors: list[str]) -> str:
    try:
        return ami_command(command)
    except (AmiError, EOFError, OSError, TimeoutError) as exc:
        ami_error = f"AMI unavailable for {command}: {exc}"

    try:
        completed = subprocess.run(
            ["asterisk", "-rx", command],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as exc:
        errors.append(f"{command} unavailable: {exc}")
        return ""
    if completed.returncode != 0:
        errors.append(
            f"{ami_error}; "
            f"{completed.stderr.strip() or completed.stdout.strip() or f'{command} failed.'}"
        )
        return ""
    return completed.stdout


def _parse_active_calls(output: str, trunks: list[dict]) -> list[dict[str, str]]:
    calls: list[dict[str, str]] = []
    trunk_names = [str(trunk["name"]) for trunk in trunks]
    seen_channels: set[str] = set()

    for raw_line in output.splitlines():
        if "!" not in raw_line:
            continue
        parts = raw_line.split("!")
        if len(parts) < 9:
            continue

        channel = parts[0].strip()
        if channel in seen_channels:
            continue
        context = parts[1].strip()
        to_number = parts[2].strip() or "-"
        state = parts[4].strip()
        dial_data = parts[6].strip() if len(parts) > 6 else ""
        caller_id = parts[7].strip() or _number_from_channel(channel) or "-"
        duration = parts[8].strip() or "00:00:00"
        bridged_to = parts[11].strip() if len(parts) > 11 else ""
        seen_channels.add(channel)
        if bridged_to:
            seen_channels.add(bridged_to)
        if _is_internal_dialed_leg(context, channel, to_number, caller_id, state, bridged_to):
            continue
        trunk = _infer_trunk(channel, bridged_to, dial_data, trunk_names)

        calls.append(
            {
                "id": channel,
                "from": caller_id,
                "to": to_number,
                "direction": _simple_direction(context, channel, bridged_to, trunk),
                "duration": duration,
                "status": _simple_call_status(state),
                "status_class": _call_status_class(state),
                "trunk": trunk or "-",
            }
        )

    return calls


def _number_from_channel(channel: str) -> str:
    match = re.search(r"PJSIP/([^-/]+)", channel)
    return match.group(1) if match else ""


def _is_internal_dialed_leg(
    context: str,
    channel: str,
    to_number: str,
    caller_id: str,
    state: str,
    bridged_to: str,
) -> bool:
    endpoint = _number_from_channel(channel)
    return (
        context == "omnipbx-internal"
        and not bridged_to
        and state.strip().lower() in {"ring", "ringing"}
        and endpoint
        and endpoint == to_number
        and caller_id == to_number
    )


def _infer_trunk(channel: str, bridged_to: str, dial_data: str, trunk_names: list[str]) -> str:
    haystack = f"{channel} {bridged_to} {dial_data}"
    for name in trunk_names:
        if re.search(rf"(^|[/@\s-]){re.escape(name)}($|[/@\s-])", haystack):
            return name
    return ""


def _simple_direction(context: str, channel: str, bridged_to: str, trunk: str) -> str:
    context_lower = context.lower()
    if context_lower.startswith("from-trunk"):
        return "Incoming"
    if context_lower == "from-internal-trunks" or (trunk and f"@{trunk}" in bridged_to):
        return "Outgoing"
    if trunk and channel.startswith(f"PJSIP/{trunk}"):
        return "Incoming"
    if trunk:
        return "Outgoing"
    return "Internal"


def _simple_call_status(state: str) -> str:
    normalized = state.strip().lower()
    if normalized == "up":
        return "Connected"
    if normalized in {"ring", "ringing"}:
        return "Ringing"
    if normalized == "busy":
        return "Busy"
    return "Starting"


def _call_status_class(state: str) -> str:
    normalized = state.strip().lower()
    if normalized == "up":
        return "online"
    if normalized in {"ring", "ringing"}:
        return "warn"
    if normalized == "busy":
        return "busy"
    return "unknown"


def _extensions_on_call(active_calls: list[dict[str, str]]) -> set[str]:
    values: set[str] = set()
    for call in active_calls:
        for key in ("from", "to"):
            value = str(call.get(key) or "")
            if value.isdigit():
                values.add(value)
    return values


def _unknown_status_snapshot(extensions: list[dict]) -> dict[str, object]:
    return {
        "extensions": [
            {
                "extension": extension["extension"],
                "display_name": extension["display_name"],
                "enabled": extension["enabled"],
                "status": "Unknown",
            }
            for extension in extensions
        ],
        "summary": {
            "extensions_total": len(extensions),
            "extensions_online": 0,
            "extensions_offline": 0,
            "extensions_unknown": len(extensions),
        },
    }


def _build_active_users(
    extension_rows: list[dict],
    profiles: dict[str, dict],
    extensions_on_call: set[str],
) -> list[dict[str, str]]:
    users: list[dict[str, str]] = []
    status_rank = {"On Call": 0, "Online": 1, "Unknown": 2, "Offline": 3}
    for row in extension_rows:
        extension = row["extension"]
        profile = profiles.get(extension, {})
        status = "On Call" if extension in extensions_on_call else row.get("status", "Unknown")
        users.append(
            {
                "name": row.get("display_name") or f"User {extension}",
                "extension": extension,
                "group": profile.get("group_name") or "Ungrouped",
                "status": status,
                "status_class": _user_status_class(status),
                "initial": (row.get("display_name") or extension)[:1].upper(),
            }
        )
    return sorted(users, key=lambda user: (status_rank.get(user["status"], 4), user["extension"]))


def _user_status_class(status: str) -> str:
    return {
        "Online": "online",
        "On Call": "on-call",
        "Offline": "offline",
        "Unknown": "unknown",
    }.get(status, "unknown")


def _parse_registration_status(output: str) -> dict[str, str]:
    statuses: dict[str, str] = {}
    for raw_line in output.splitlines():
        line = raw_line.strip()
        if not line or line.startswith(("=", "<", "Objects found")):
            continue
        name_match = re.search(r"\breg-([^\s/]+)", line)
        if not name_match:
            continue
        if "Registered" in line:
            statuses[name_match.group(1)] = "Registered"
        elif "Rejected" in line:
            statuses[name_match.group(1)] = "Rejected"
        elif "Unregistered" in line:
            statuses[name_match.group(1)] = "Unregistered"
        else:
            statuses[name_match.group(1)] = line.split()[-1]
    return statuses


def _build_trunk_rows(
    trunks: list[dict],
    registration_status: dict[str, str],
    active_calls: list[dict[str, str]],
) -> list[dict[str, str | int]]:
    rows: list[dict[str, str | int]] = []
    for trunk in trunks:
        name = trunk["name"]
        active_count = len([call for call in active_calls if call.get("trunk") == name])
        registered_state = registration_status.get(name, "")
        status, message = _trunk_status_message(trunk, registered_state)
        rows.append(
            {
                "name": name,
                "provider": trunk.get("provider_name") or trunk.get("host") or "-",
                "status": status,
                "status_class": "online" if status == "Online" else "offline" if status == "Offline" else "warn",
                "active_calls": active_count,
                "last_registered": "Now" if registered_state == "Registered" else "-",
                "message": message,
            }
        )
    return rows


def _trunk_status_message(trunk: dict, registered_state: str) -> tuple[str, str]:
    if not trunk.get("enabled"):
        return "Offline", "Disabled"
    if not trunk.get("register_enabled"):
        return "Warning", "IP based connection"
    if registered_state == "Registered":
        return "Online", "Ready"
    if registered_state:
        return "Offline", "Waiting for provider"
    return "Warning", "No registration status yet"


def _system_status(errors: list[str], trunks: list[dict]) -> dict[str, str]:
    offline_trunks = [trunk for trunk in trunks if trunk["status"] == "Offline"]
    if errors:
        return {"label": "Needs Attention", "class": "warning", "message": "Some live data is unavailable."}
    if offline_trunks:
        return {"label": "Needs Attention", "class": "warning", "message": "One or more trunks need attention."}
    return {"label": "Healthy", "class": "online", "message": "PBX activity is reporting normally."}


def _notifications(
    summary: dict[str, object],
    errors: list[str],
    trunks: list[dict],
) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    for error in errors[:2]:
        items.append(
            {
                "severity": "warning",
                "title": "Live data limited",
                "description": error,
                "time": "Now",
            }
        )
    offline_count = len([trunk for trunk in trunks if trunk["status"] == "Offline"])
    if offline_count:
        items.append(
            {
                "severity": "danger",
                "title": "Trunk needs attention",
                "description": f"{offline_count} trunk{'s' if offline_count != 1 else ''} offline.",
                "time": "Now",
            }
        )
    if int(summary["active_calls"]) == 0 and not items:
        items.append(
            {
                "severity": "success",
                "title": "Quiet right now",
                "description": "No active calls at this moment.",
                "time": "Now",
            }
        )
    return items[:5]
