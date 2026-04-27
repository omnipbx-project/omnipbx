from datetime import datetime, UTC
import re
import subprocess

import psycopg

from app.services.extensions import list_extensions


ONLINE_STATES = {"avail", "available", "ok", "reachable", "registered", "online", "lagged"}
OFFLINE_STATES = {"unavail", "unavailable", "nonqual", "unknown", "unregistered", "rejected", "offline"}


def run_asterisk_command(command: str) -> str:
    completed = subprocess.run(
        ["asterisk", "-rx", command],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or completed.stdout.strip() or "Asterisk CLI command failed.")
    return completed.stdout


def normalize_state(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip().lower()
    return normalized or None


def derive_status(endpoint_state: str | None, contact_status: str | None) -> str:
    endpoint_normalized = normalize_state(endpoint_state)
    contact_normalized = normalize_state(contact_status)

    if contact_normalized in ONLINE_STATES or endpoint_normalized in ONLINE_STATES:
        return "Online"
    if contact_normalized in OFFLINE_STATES or endpoint_normalized in OFFLINE_STATES:
        return "Offline"
    return "Unknown"


def parse_endpoint_output(output: str) -> dict[str, dict[str, str]]:
    endpoint_map: dict[str, dict[str, str]] = {}
    pattern = re.compile(r"^\s*Endpoint:\s+", re.MULTILINE)
    matches = list(pattern.finditer(output))

    for index, match in enumerate(matches):
        start = match.start()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(output)
        block = output[start:end].strip()
        lines = [line.rstrip() for line in block.splitlines() if line.strip()]
        if not lines:
            continue

        first_line = re.sub(r"^\s*Endpoint:\s*", "", lines[0], count=1).strip()
        header_match = re.match(
            r"^(?P<name>\S+)\s{2,}(?P<state>.+?)\s{2,}(?P<channels>\d+\s+of\s+\S+)$",
            first_line,
        )
        if not header_match:
            continue

        endpoint_name = header_match.group("name")
        endpoint_key = endpoint_name.split("/", 1)[0]
        row = {
            "endpoint_name": endpoint_name,
            "endpoint_state": header_match.group("state").strip(),
            "channels": header_match.group("channels").strip(),
            "aor": "",
            "contact_uri": "",
            "contact_status": "",
            "contact_rtt": "",
            "transport": "",
        }

        for line in lines[1:]:
            stripped = line.strip()
            if stripped.startswith("Aor:"):
                content = stripped.split(":", 1)[1].strip()
                row["aor"] = content.rsplit(None, 1)[0] if " " in content else content
            elif stripped.startswith("Contact:"):
                content = stripped.split(":", 1)[1].strip()
                parts = content.split()
                if parts:
                    row["contact_uri"] = parts[0]
                if len(parts) >= 3:
                    row["contact_status"] = parts[2]
                if len(parts) >= 4:
                    row["contact_rtt"] = parts[3]
            elif stripped.startswith("Transport:"):
                row["transport"] = stripped.split(":", 1)[1].strip().split()[0]

        endpoint_map[endpoint_key] = row

    return endpoint_map


def collect_status_snapshot(connection: psycopg.Connection) -> dict[str, object]:
    extensions = list_extensions(connection)
    output = run_asterisk_command("pjsip show endpoints")
    endpoint_map = parse_endpoint_output(output)

    rows: list[dict[str, str | bool]] = []
    online = 0
    offline = 0
    unknown = 0

    for extension in extensions:
        endpoint_data = endpoint_map.get(extension["extension"], {})
        status = derive_status(
            endpoint_data.get("endpoint_state"),
            endpoint_data.get("contact_status"),
        )
        if status == "Online":
            online += 1
        elif status == "Offline":
            offline += 1
        else:
            unknown += 1

        rows.append(
            {
                "extension": extension["extension"],
                "display_name": extension["display_name"],
                "enabled": extension["enabled"],
                "status": status,
                "endpoint_state": endpoint_data.get("endpoint_state", "Unknown"),
                "channels": endpoint_data.get("channels", "0 of inf"),
                "aor": endpoint_data.get("aor", extension["extension"]),
                "contact_uri": endpoint_data.get("contact_uri", ""),
                "contact_status": endpoint_data.get("contact_status", ""),
                "contact_rtt": endpoint_data.get("contact_rtt", ""),
                "transport": endpoint_data.get("transport", "transport-udp"),
            }
        )

    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "extensions": rows,
        "summary": {
            "extensions_total": len(rows),
            "extensions_online": online,
            "extensions_offline": offline,
            "extensions_unknown": unknown,
        },
    }
