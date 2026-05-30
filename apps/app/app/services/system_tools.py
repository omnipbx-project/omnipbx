from __future__ import annotations

import os
import json
import shutil
import socket
import subprocess
import time
from pathlib import Path
from urllib import request as urllib_request
from urllib import error as urllib_error

import psycopg
from psycopg.rows import dict_row

from app.core.settings import get_settings


ASTERISK_ALLOWED_PREFIXES = (
    "core show",
    "core reload",
    "dialplan show",
    "dialplan reload",
    "pjsip show",
    "pjsip reload",
    "queue show",
    "module show",
    "logger rotate",
)

LOG_FILES = {
    "asterisk": Path("/var/log/asterisk/full"),
    "asterisk_messages": Path("/var/log/asterisk/messages"),
    "fail2ban": Path("/var/log/fail2ban.log"),
    "app": Path("/var/log/omnipbx/app.log"),
}

_CPU_PREVIOUS_SAMPLE: dict[str, float] | None = None


def collect_system_usage() -> dict[str, object]:
    cpu = _cpu_percent()
    memory = _memory_percent()
    disk = shutil.disk_usage("/")
    load = os.getloadavg() if hasattr(os, "getloadavg") else (0.0, 0.0, 0.0)
    pressure = _system_pressure(load)
    return {
        "cpu": cpu,
        "ram": memory["percent"],
        "disk": round((disk.used / disk.total) * 100, 1) if disk.total else 0,
        "disk_free": _bytes_label(disk.free),
        "disk_used": _bytes_label(disk.used),
        "disk_total": _bytes_label(disk.total),
        "ram_used": memory["used_label"],
        "ram_total": memory["total_label"],
        "load": ", ".join(f"{value:.2f}" for value in load),
        "system_pressure": pressure["label"],
        "system_pressure_detail": pressure["detail"],
        "uptime": _uptime_label(),
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }


def build_advanced_snapshot(connection: psycopg.Connection) -> dict[str, object]:
    agent_status = host_security_agent_action("status", dry_run=True)
    return {
        "usage": collect_system_usage(),
        "logs": read_logs(),
        "asterisk": {
            "suggested_commands": [
                "core show channels concise",
                "pjsip show endpoints",
                "pjsip show registrations",
                "queue show",
                "dialplan show omnipbx-internal",
            ],
        },
        "network": collect_network_snapshot(connection),
        "security_rules": list_security_rules(connection),
        "custom_config": get_custom_config(connection),
        "services": collect_service_snapshot(),
        "host_security_agent": agent_status,
    }


def read_logs(source: str = "asterisk", *, limit: int = 120, keyword: str = "") -> dict[str, object]:
    path = LOG_FILES.get(source, LOG_FILES["asterisk"])
    lines = _tail_file(path, limit=limit * 3)
    keyword = keyword.strip().lower()
    if keyword:
        lines = [line for line in lines if keyword in line.lower()]
    entries = [_parse_log_line(line) for line in lines[-limit:]]
    return {
        "source": source,
        "path": str(path),
        "lines": lines[-limit:],
        "entries": entries,
        "available": path.exists(),
    }


def run_asterisk_cli(command: str) -> dict[str, object]:
    cleaned = " ".join((command or "").strip().split())
    if not cleaned:
        return {"ok": False, "output": "Enter an Asterisk command."}
    if not any(cleaned.startswith(prefix) for prefix in ASTERISK_ALLOWED_PREFIXES):
        return {
            "ok": False,
            "output": "Command not allowed here. Use show, reload, queue, module, or logger commands.",
        }
    completed = subprocess.run(["asterisk", "-rx", cleaned], capture_output=True, text=True, check=False, timeout=8)
    output = completed.stdout.strip() or completed.stderr.strip() or "No output."
    return {"ok": completed.returncode == 0, "command": cleaned, "output": output}


def collect_network_snapshot(connection: psycopg.Connection) -> dict[str, object]:
    settings = get_settings()
    rows = get_network_settings(connection)
    agent_status = host_security_agent_action("status", dry_run=True)
    host_network = agent_status.get("network") if agent_status.get("connected") else None
    host_ip = host_network.get("local_ip") if isinstance(host_network, dict) else ""
    local_ip = str(host_ip or _local_ip())
    ip_note = "Host LAN address" if host_ip else "Detected inside PBX container"
    ports = [
        {"label": "SIP", "port": settings.sip_port, "protocol": "udp"},
        {"label": "Web", "port": settings.http_port, "protocol": "tcp"},
        {"label": "Public HTTP", "port": settings.public_http_port, "protocol": "tcp"},
        {"label": "Public HTTPS", "port": settings.public_https_port, "protocol": "tcp"},
    ]
    return {
        "hostname": socket.gethostname(),
        "local_ip": local_ip,
        "local_ip_note": ip_note,
        "settings": rows,
        "ports": ports,
    }


def run_network_check(host: str, port: int | None = None) -> dict[str, object]:
    host = (host or "").strip()
    if not host:
        return {"ok": False, "output": "Enter a host or IP."}
    if port:
        started = time.monotonic()
        try:
            with socket.create_connection((host, int(port)), timeout=4):
                elapsed = round((time.monotonic() - started) * 1000)
                return {"ok": True, "output": f"{host}:{port} is reachable in {elapsed} ms."}
        except OSError as exc:
            return {"ok": False, "output": f"{host}:{port} is not reachable: {exc}"}
    try:
        resolved = socket.gethostbyname(host)
        return {"ok": True, "output": f"{host} resolves to {resolved}."}
    except OSError as exc:
        return {"ok": False, "output": f"DNS lookup failed: {exc}"}


def collect_service_snapshot() -> dict[str, object]:
    agent_status = host_security_agent_action("status", dry_run=True)
    if agent_status.get("connected"):
        return {
            "fail2ban": _agent_service_status(agent_status, "fail2ban"),
            "firewall": _agent_service_status(agent_status, "firewall"),
        }
    return {
        "fail2ban": _optional_command_status("fail2ban-client", ["fail2ban-client", "status"], "Fail2ban is not installed in this container/host."),
        "firewall": _firewall_status(),
    }


def _agent_service_status(agent_status: dict[str, object], key: str) -> dict[str, object]:
    service = agent_status.get(key)
    if isinstance(service, dict):
        return {
            "installed": bool(service.get("installed", service.get("ok"))),
            "ok": bool(service.get("ok")),
            "output": str(service.get("output") or "Connected through host security agent."),
        }
    return {"installed": False, "ok": False, "output": "No agent status reported."}


def host_security_agent_action(action: str, *, value: str = "", dry_run: bool = True) -> dict[str, object]:
    settings = get_settings()
    if not settings.host_security_agent_url or not settings.host_security_agent_token:
        return {"connected": False, "ok": False, "output": "Host security agent is not configured."}
    url = settings.host_security_agent_url.rstrip("/") + "/v1/action"
    payload = json.dumps({"action": action, "value": value, "dry_run": dry_run}).encode("utf-8")
    req = urllib_request.Request(
        url,
        data=payload,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "X-OmniPBX-Agent-Token": settings.host_security_agent_token,
        },
    )
    try:
        with urllib_request.urlopen(req, timeout=settings.host_security_agent_timeout_seconds) as response:
            data = json.loads(response.read().decode("utf-8") or "{}")
            return {"connected": True, **data}
    except (OSError, urllib_error.URLError, TimeoutError) as exc:
        return {"connected": False, "ok": False, "output": f"Host security agent is unavailable: {exc}"}


def apply_security_rule_to_agent(*, rule_type: str, value: str, dry_run: bool = True) -> dict[str, object]:
    action_by_type = {
        "ip_whitelist": "allow_ip",
        "ip_blocklist": "block_ip",
    }
    action = action_by_type.get(rule_type)
    if not action:
        return {"connected": False, "ok": False, "output": "This rule type does not apply to the host firewall."}
    return host_security_agent_action(action, value=value, dry_run=dry_run)


def list_security_rules(connection: psycopg.Connection) -> list[dict]:
    with connection.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT id, rule_type, value, note, enabled, TO_CHAR(created_at, 'YYYY-MM-DD HH24:MI:SS') AS created_at
            FROM advanced_security_rules
            ORDER BY rule_type, value
            """
        )
        return [dict(row) for row in cursor.fetchall()]


def save_security_rule(connection: psycopg.Connection, *, rule_type: str, value: str, note: str = "", enabled: bool = True) -> None:
    if rule_type not in {"number_block", "ip_whitelist", "ip_blocklist"}:
        raise ValueError("Unknown rule type.")
    value = value.strip()
    if not value:
        raise ValueError("Rule value is required.")
    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO advanced_security_rules (rule_type, value, note, enabled)
            VALUES (%(rule_type)s, %(value)s, %(note)s, %(enabled)s)
            ON CONFLICT (rule_type, value) DO UPDATE
            SET note = EXCLUDED.note, enabled = EXCLUDED.enabled, updated_at = NOW()
            """,
            {"rule_type": rule_type, "value": value, "note": note.strip() or None, "enabled": enabled},
        )


def delete_security_rule(connection: psycopg.Connection, rule_id: int) -> bool:
    with connection.cursor(row_factory=dict_row) as cursor:
        cursor.execute("DELETE FROM advanced_security_rules WHERE id = %(id)s RETURNING id", {"id": rule_id})
        return bool(cursor.fetchone())


def get_custom_config(connection: psycopg.Connection) -> dict[str, dict]:
    with connection.cursor(row_factory=dict_row) as cursor:
        cursor.execute("SELECT config_key, content, enabled, updated_at FROM advanced_custom_config ORDER BY config_key")
        return {row["config_key"]: dict(row) for row in cursor.fetchall()}


def save_custom_config(connection: psycopg.Connection, *, config_key: str, content: str, enabled: bool) -> None:
    if config_key not in {"pjsip", "dialplan"}:
        raise ValueError("Unknown custom config type.")
    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO advanced_custom_config (config_key, content, enabled, updated_at)
            VALUES (%(config_key)s, %(content)s, %(enabled)s, NOW())
            ON CONFLICT (config_key) DO UPDATE
            SET content = EXCLUDED.content, enabled = EXCLUDED.enabled, updated_at = NOW()
            """,
            {"config_key": config_key, "content": content, "enabled": enabled},
        )


def get_network_settings(connection: psycopg.Connection) -> dict:
    with connection.cursor(row_factory=dict_row) as cursor:
        cursor.execute("SELECT trusted_ips, blocked_ips, open_ports, note FROM advanced_network_settings WHERE id = 1")
        row = cursor.fetchone()
    return dict(row) if row else {"trusted_ips": "", "blocked_ips": "", "open_ports": "", "note": ""}


def save_network_settings(connection: psycopg.Connection, *, trusted_ips: str = "", blocked_ips: str = "", open_ports: str = "", note: str = "") -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO advanced_network_settings (id, trusted_ips, blocked_ips, open_ports, note, updated_at)
            VALUES (1, %(trusted_ips)s, %(blocked_ips)s, %(open_ports)s, %(note)s, NOW())
            ON CONFLICT (id) DO UPDATE
            SET trusted_ips = EXCLUDED.trusted_ips,
                blocked_ips = EXCLUDED.blocked_ips,
                open_ports = EXCLUDED.open_ports,
                note = EXCLUDED.note,
                updated_at = NOW()
            """,
            {"trusted_ips": trusted_ips, "blocked_ips": blocked_ips, "open_ports": open_ports, "note": note},
        )


def _cpu_percent() -> float:
    cgroup = _read_cgroup_cpu_sample()
    if cgroup:
        return _cpu_percent_from_cgroup(cgroup)
    first = _read_cpu_times()
    time.sleep(0.25)
    second = _read_cpu_times()
    idle_delta = second["idle"] - first["idle"]
    total_delta = second["total"] - first["total"]
    if total_delta <= 0:
        return 0.0
    return round(100 * (1 - idle_delta / total_delta), 1)


def _cpu_percent_from_cgroup(sample: dict[str, float]) -> float:
    global _CPU_PREVIOUS_SAMPLE
    previous = _CPU_PREVIOUS_SAMPLE
    _CPU_PREVIOUS_SAMPLE = sample
    if not previous:
        fallback = _cpu_percent_from_proc()
        return fallback
    usage_delta = sample["usage_usec"] - previous["usage_usec"]
    time_delta = sample["time"] - previous["time"]
    if usage_delta < 0 or time_delta <= 0:
        return 0.0
    cpu_count = _effective_cpu_count()
    percent = (usage_delta / 1_000_000) / time_delta / cpu_count * 100
    return round(max(0.0, min(100.0, percent)), 1)


def _cpu_percent_from_proc() -> float:
    first = _read_cpu_times()
    time.sleep(0.25)
    second = _read_cpu_times()
    idle_delta = second["idle"] - first["idle"]
    total_delta = second["total"] - first["total"]
    if total_delta <= 0:
        return 0.0
    return round(100 * (1 - idle_delta / total_delta), 1)


def _read_cgroup_cpu_sample() -> dict[str, float] | None:
    path = Path("/sys/fs/cgroup/cpu.stat")
    if not path.exists():
        return None
    try:
        values = {}
        for line in path.read_text(encoding="utf-8").splitlines():
            key, value = line.split(maxsplit=1)
            values[key] = float(value)
        usage_usec = values.get("usage_usec")
    except (OSError, ValueError):
        return None
    if usage_usec is None:
        return None
    return {"usage_usec": usage_usec, "time": time.monotonic()}


def _effective_cpu_count() -> float:
    quota_path = Path("/sys/fs/cgroup/cpu.max")
    if quota_path.exists():
        try:
            quota, period = quota_path.read_text(encoding="utf-8").strip().split()[:2]
            if quota != "max" and float(period) > 0:
                return max(1.0, float(quota) / float(period))
        except (OSError, ValueError):
            pass
    return float(os.cpu_count() or 1)


def _read_cpu_times() -> dict[str, int]:
    parts = Path("/proc/stat").read_text(encoding="utf-8").splitlines()[0].split()[1:]
    values = [int(value) for value in parts]
    idle = values[3] + (values[4] if len(values) > 4 else 0)
    return {"idle": idle, "total": sum(values)}


def _memory_percent() -> dict[str, object]:
    cgroup = _cgroup_memory()
    if cgroup:
        return cgroup
    info = {}
    for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
        key, value = line.split(":", 1)
        info[key] = int(value.strip().split()[0]) * 1024
    total = info.get("MemTotal", 0)
    available = info.get("MemAvailable", 0)
    used = max(0, total - available)
    percent = round((used / total) * 100, 1) if total else 0.0
    return {"percent": percent, "used_label": _bytes_label(used), "total_label": _bytes_label(total)}


def _cgroup_memory() -> dict[str, object] | None:
    current_path = Path("/sys/fs/cgroup/memory.current")
    max_path = Path("/sys/fs/cgroup/memory.max")
    if not current_path.exists() or not max_path.exists():
        return None
    try:
        used = int(current_path.read_text(encoding="utf-8").strip())
        max_raw = max_path.read_text(encoding="utf-8").strip()
        total = int(max_raw) if max_raw != "max" else 0
    except (OSError, ValueError):
        return None
    if total <= 0:
        return None
    percent = round((used / total) * 100, 1)
    return {"percent": percent, "used_label": _bytes_label(used), "total_label": _bytes_label(total)}


def _uptime_label() -> str:
    try:
        seconds = int(float(Path("/proc/uptime").read_text(encoding="utf-8").split()[0]))
    except OSError:
        return "Unknown"
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, _ = divmod(rem, 60)
    if days:
        return f"{days}d {hours}h"
    if hours:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"


def _system_pressure(load: tuple[float, float, float]) -> dict[str, str]:
    cores = _effective_cpu_count()
    ratio = load[0] / cores if cores else 0.0
    if ratio < 0.7:
        return {"label": "Normal", "detail": "System has room for calls."}
    if ratio < 1.0:
        return {"label": "Busy", "detail": "System is working harder than usual."}
    return {"label": "High", "detail": "System may feel slow."}


def _tail_file(path: Path, *, limit: int) -> list[str]:
    if not path.exists():
        return []


def _parse_log_line(line: str) -> dict[str, str]:
    cleaned = line.strip()
    level = "INFO"
    upper = cleaned.upper()
    if "ERROR" in upper or "FAILED" in upper:
        level = "ERROR"
    elif "WARNING" in upper or "WARN" in upper:
        level = "WARN"
    elif "NOTICE" in upper:
        level = "NOTICE"

    timestamp = ""
    message = cleaned
    if cleaned.startswith("[") and "]" in cleaned:
        timestamp, message = cleaned[1:].split("]", 1)
        message = message.strip()
    return {"time": timestamp or "-", "level": level, "message": message or cleaned}
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            return handle.readlines()[-limit:]
    except OSError:
        return []


def _local_ip() -> str:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("8.8.8.8", 80))
            return sock.getsockname()[0]
    except OSError:
        return "Unknown"


def _command_status(command: list[str]) -> dict[str, object]:
    try:
        completed = subprocess.run(command, capture_output=True, text=True, check=False, timeout=6)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"ok": False, "output": str(exc)}
    return {
        "installed": True,
        "ok": completed.returncode == 0,
        "output": (completed.stdout.strip() or completed.stderr.strip() or "No output.")[:4000],
    }


def _optional_command_status(binary: str, command: list[str], missing_message: str) -> dict[str, object]:
    if not shutil.which(binary):
        return {"installed": False, "ok": False, "output": missing_message}
    return _command_status(command)


def _firewall_status() -> dict[str, object]:
    if shutil.which("ufw"):
        return _command_status(["ufw", "status"])
    if shutil.which("firewall-cmd"):
        return _command_status(["firewall-cmd", "--state"])
    if shutil.which("iptables"):
        result = _command_status(["iptables", "-S"])
        if not result["ok"] and "Permission denied" in str(result["output"]):
            result["output"] = "Firewall CLI is present, but this container does not have permission to read host firewall rules."
        return result
    return {"installed": False, "ok": False, "output": "No supported firewall CLI found in this container/host."}


def _bytes_label(value: int | float) -> str:
    size = float(value or 0)
    units = ["B", "KB", "MB", "GB", "TB"]
    unit = units[0]
    for unit in units:
        if size < 1024 or unit == units[-1]:
            break
        size = size / 1024
    if unit == "B":
        return f"{int(size)} {unit}"
    return f"{size:.1f} {unit}"
