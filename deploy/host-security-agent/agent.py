from __future__ import annotations

import ipaddress
import json
import os
import shutil
import subprocess
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


HOST = os.environ.get("OMNIPBX_SECURITY_AGENT_HOST", "127.0.0.1")
PORT = int(os.environ.get("OMNIPBX_SECURITY_AGENT_PORT", "8765"))
TOKEN = os.environ.get("OMNIPBX_SECURITY_AGENT_TOKEN", "")
EMERGENCY_ALLOWLIST = [
    item.strip()
    for item in os.environ.get("OMNIPBX_SECURITY_AGENT_EMERGENCY_ALLOWLIST", "127.0.0.1,::1").split(",")
    if item.strip()
]

READ_ACTIONS = {"status", "firewall_status", "fail2ban_status"}
WRITE_ACTIONS = {"allow_ip", "block_ip", "unblock_ip", "fail2ban_unban"}
ALL_ACTIONS = READ_ACTIONS | WRITE_ACTIONS


class Handler(BaseHTTPRequestHandler):
    server_version = "OmniPBXHostSecurityAgent/1.0"

    def do_GET(self) -> None:
        if self.path not in {"/health", "/v1/health"}:
            self._send(404, {"ok": False, "error": "Not found"})
            return
        self._send(200, {"ok": True, "service": "omnipbx-host-security-agent"})

    def do_POST(self) -> None:
        if self.path != "/v1/action":
            self._send(404, {"ok": False, "error": "Not found"})
            return
        if TOKEN and self.headers.get("X-OmniPBX-Agent-Token") != TOKEN:
            self._send(401, {"ok": False, "error": "Unauthorized"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
            response = handle_action(payload)
            self._send(200 if response.get("ok") else 400, response)
        except Exception as exc:
            self._send(500, {"ok": False, "error": str(exc)})

    def log_message(self, format: str, *args) -> None:
        print(format % args)

    def _send(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, sort_keys=True).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def handle_action(payload: dict) -> dict:
    action = str(payload.get("action") or "").strip()
    if action not in ALL_ACTIONS:
        return {"ok": False, "error": "Unsupported action"}
    dry_run = bool(payload.get("dry_run", True))

    if action == "status":
        return {
            "ok": True,
            "dry_run": dry_run,
            "firewall": firewall_status(),
            "fail2ban": fail2ban_status(),
            "emergency_allowlist": EMERGENCY_ALLOWLIST,
        }
    if action == "firewall_status":
        return {"ok": True, "firewall": firewall_status()}
    if action == "fail2ban_status":
        return {"ok": True, "fail2ban": fail2ban_status()}

    value = str(payload.get("value") or "").strip()
    if not value:
        return {"ok": False, "error": "IP or CIDR value is required"}
    try:
        parsed = ipaddress.ip_network(value, strict=False)
    except ValueError:
        return {"ok": False, "error": "Invalid IP/CIDR"}
    if action in {"block_ip"} and is_emergency_allowed(parsed):
        return {"ok": False, "error": "Refusing to block emergency allowlist IP/network"}

    if action == "allow_ip":
        return firewall_allow(str(parsed), dry_run=dry_run)
    if action == "block_ip":
        return firewall_block(str(parsed), dry_run=dry_run)
    if action == "unblock_ip":
        return firewall_unblock(str(parsed), dry_run=dry_run)
    if action == "fail2ban_unban":
        return fail2ban_unban(str(parsed.network_address), dry_run=dry_run)
    return {"ok": False, "error": "Unsupported action"}


def is_emergency_allowed(network: ipaddress._BaseNetwork) -> bool:
    for item in EMERGENCY_ALLOWLIST:
        try:
            emergency = ipaddress.ip_network(item, strict=False)
        except ValueError:
            continue
        if network.overlaps(emergency):
            return True
    return False


def firewall_status() -> dict:
    if shutil.which("ufw"):
        return run(["ufw", "status"], dry_run=False)
    if shutil.which("iptables"):
        return run(["iptables", "-S"], dry_run=False)
    return {"ok": False, "installed": False, "output": "No supported firewall CLI found"}


def firewall_allow(value: str, *, dry_run: bool) -> dict:
    if shutil.which("ufw"):
        return run(["ufw", "allow", "from", value], dry_run=dry_run)
    if shutil.which("iptables"):
        return run(["iptables", "-I", "INPUT", "-s", value, "-j", "ACCEPT"], dry_run=dry_run)
    return {"ok": False, "installed": False, "output": "No supported firewall CLI found"}


def firewall_block(value: str, *, dry_run: bool) -> dict:
    if shutil.which("ufw"):
        return run(["ufw", "deny", "from", value], dry_run=dry_run)
    if shutil.which("iptables"):
        return run(["iptables", "-I", "INPUT", "-s", value, "-j", "DROP"], dry_run=dry_run)
    return {"ok": False, "installed": False, "output": "No supported firewall CLI found"}


def firewall_unblock(value: str, *, dry_run: bool) -> dict:
    if shutil.which("ufw"):
        return run(["ufw", "delete", "deny", "from", value], dry_run=dry_run)
    if shutil.which("iptables"):
        return run(["iptables", "-D", "INPUT", "-s", value, "-j", "DROP"], dry_run=dry_run)
    return {"ok": False, "installed": False, "output": "No supported firewall CLI found"}


def fail2ban_status() -> dict:
    if not shutil.which("fail2ban-client"):
        return {"ok": False, "installed": False, "output": "fail2ban-client is not installed"}
    if not os.path.exists("/var/run/fail2ban/fail2ban.sock"):
        return {
            "ok": False,
            "installed": True,
            "output": "Fail2ban is installed, but the host Fail2ban service is not running or its socket is not mounted.",
        }
    result = run(["fail2ban-client", "status"], dry_run=False)
    if not result.get("ok"):
        result["output"] = "Fail2ban is installed, but the host Fail2ban service is not ready."
    return result


def fail2ban_unban(value: str, *, dry_run: bool) -> dict:
    if not shutil.which("fail2ban-client"):
        return {"ok": False, "installed": False, "output": "fail2ban-client is not installed"}
    return run(["fail2ban-client", "unban", value], dry_run=dry_run)


def run(command: list[str], *, dry_run: bool) -> dict:
    if dry_run:
        return {"ok": True, "installed": True, "dry_run": True, "command": command, "output": "Dry run only. No host changes applied."}
    completed = subprocess.run(command, capture_output=True, text=True, check=False, timeout=8)
    return {
        "ok": completed.returncode == 0,
        "installed": True,
        "dry_run": False,
        "command": command,
        "output": (completed.stdout.strip() or completed.stderr.strip() or "No output.")[:4000],
    }


if __name__ == "__main__":
    if not TOKEN:
        print("WARNING: OMNIPBX_SECURITY_AGENT_TOKEN is empty. Set a token before production use.")
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"OmniPBX host security agent listening on {HOST}:{PORT}")
    server.serve_forever()
