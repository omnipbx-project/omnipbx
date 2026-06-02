import socket
import threading
import time
from copy import deepcopy
from collections.abc import Callable

from app.core.settings import get_settings


INTERESTING_EVENTS = {
    "BridgeCreate",
    "BridgeDestroy",
    "BridgeEnter",
    "BridgeLeave",
    "ContactStatus",
    "DeviceStateChange",
    "EndpointDetailComplete",
    "Hangup",
    "Newchannel",
    "Newstate",
    "PeerStatus",
    "Registry",
    "Reload",
}


class LiveEventHub:
    def __init__(self) -> None:
        self._condition = threading.Condition()
        self._version = 0
        self._last_event = "startup"
        self._running = False
        self._thread: threading.Thread | None = None
        self._snapshot_loader: Callable[[], dict[str, object]] | None = None
        self._snapshot: dict[str, object] | None = None
        self._snapshot_refreshing = False

    @property
    def version(self) -> int:
        with self._condition:
            return self._version

    def set_snapshot_loader(self, loader: Callable[[], dict[str, object]]) -> None:
        with self._condition:
            self._snapshot_loader = loader

    def get_snapshot(self) -> dict[str, object] | None:
        with self._condition:
            if self._snapshot is None:
                return None
            return deepcopy(self._snapshot)

    def refresh_snapshot_async(self, event_name: str = "snapshot") -> None:
        with self._condition:
            loader = self._snapshot_loader
            if not loader or self._snapshot_refreshing:
                return
            self._snapshot_refreshing = True

        thread = threading.Thread(
            target=self._refresh_snapshot,
            args=(loader, event_name),
            name="omnipbx-live-snapshot",
            daemon=True,
        )
        thread.start()

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._running = True
        self._thread = threading.Thread(target=self._run, name="omnipbx-ami-events", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        self.notify("shutdown")

    def notify(self, event_name: str) -> None:
        self.refresh_snapshot_async(event_name)
        with self._condition:
            self._version += 1
            self._last_event = event_name
            self._condition.notify_all()

    def notify_ami_event(self, event_name: str, message: dict[str, str]) -> None:
        changed = self._apply_presence_event(event_name, message)
        self.refresh_snapshot_async(event_name)
        with self._condition:
            self._version += 1
            self._last_event = f"{event_name}:fast" if changed else event_name
            self._condition.notify_all()

    def wait_for_change(self, version: int, timeout: float = 25.0) -> tuple[int, str]:
        with self._condition:
            if self._version == version:
                self._condition.wait(timeout=timeout)
            return self._version, self._last_event

    def _run(self) -> None:
        while self._running:
            try:
                self._listen_once()
            except (OSError, TimeoutError, RuntimeError):
                self.notify("ami-disconnected")
                time.sleep(3)

    def _listen_once(self) -> None:
        settings = get_settings()
        with socket.create_connection((settings.ami_host, settings.ami_port), timeout=settings.ami_timeout_seconds) as sock:
            sock.settimeout(settings.ami_timeout_seconds)
            stream = sock.makefile("rwb", buffering=0)
            _read_message(stream)
            _send_message(
                stream,
                {
                    "Action": "Login",
                    "Username": settings.ami_username,
                    "Secret": settings.ami_password,
                    "Events": "on",
                },
            )
            response = _read_message(stream)
            if response.get("Response") != "Success":
                raise RuntimeError(response.get("Message", "AMI event login failed."))
            sock.settimeout(None)
            self.notify("ami-connected")

            while self._running:
                message = _read_message(stream)
                if not message:
                    raise RuntimeError("AMI event stream closed.")
                event_name = message.get("Event", "")
                if event_name in INTERESTING_EVENTS:
                    self.notify_ami_event(event_name, message)

    def _refresh_snapshot(self, loader: Callable[[], dict[str, object]], event_name: str) -> None:
        try:
            snapshot = loader()
        except Exception:
            with self._condition:
                self._snapshot_refreshing = False
            return

        with self._condition:
            self._snapshot = snapshot
            self._snapshot_refreshing = False
            self._version += 1
            self._last_event = event_name
            self._condition.notify_all()

    def _apply_presence_event(self, event_name: str, message: dict[str, str]) -> bool:
        extension = _extension_from_event(message)
        if not extension:
            return False
        status = _status_from_event(event_name, message)
        if not status:
            return False

        with self._condition:
            if not self._snapshot:
                return False
            users = self._snapshot.get("active_users")
            if not isinstance(users, list):
                return False
            changed = False
            for user in users:
                if not isinstance(user, dict) or str(user.get("extension")) != extension:
                    continue
                if user.get("status") == "On Call" and status == "Online" and event_name not in {"Hangup", "BridgeLeave"}:
                    return False
                if user.get("status") == status:
                    return False
                user["status"] = status
                user["status_class"] = _status_class(status)
                changed = True
                break
            if changed:
                summary = self._snapshot.get("summary")
                if isinstance(summary, dict):
                    summary["active_users"] = len(
                        [
                            user
                            for user in users
                            if isinstance(user, dict) and user.get("status") in {"Online", "On Call", "Ringing"}
                        ]
                    )
            return changed


def _send_message(stream, fields: dict[str, str]) -> None:
    payload = "".join(f"{key}: {value}\r\n" for key, value in fields.items()) + "\r\n"
    stream.write(payload.encode("utf-8"))


def _read_message(stream) -> dict[str, str]:
    message: dict[str, str] = {}
    while True:
        raw_line = stream.readline()
        if not raw_line:
            break
        line = raw_line.decode("utf-8", errors="replace").rstrip("\r\n")
        if not line:
            break
        key, separator, value = line.partition(":")
        if separator:
            message[key] = value.strip()
    return message


def _extension_from_event(message: dict[str, str]) -> str:
    for key in ("EndpointName", "AOR", "Peer", "Device", "Channel", "DestChannel", "ConnectedLineNum", "CallerIDNum"):
        value = (message.get(key) or "").strip()
        if not value:
            continue
        if "/" in value:
            value = value.split("/", 1)[1]
        value = value.split(";", 1)[0].split("@", 1)[0].split("-", 1)[0].strip()
        if value.isdigit():
            return value
    return ""


def _status_from_event(event_name: str, message: dict[str, str]) -> str:
    if event_name in {"Newchannel", "Newstate"}:
        return _channel_status(message.get("ChannelStateDesc") or message.get("State"))
    if event_name in {"Hangup", "BridgeLeave"}:
        return "Online"
    if event_name == "ContactStatus":
        return _contact_status(message.get("ContactStatus"), webphone=_is_webphone_contact_event(message))
    if event_name == "PeerStatus":
        return _contact_status(message.get("PeerStatus"))
    if event_name == "DeviceStateChange":
        return _device_status(message.get("State"))
    return ""


def _is_webphone_contact_event(message: dict[str, str]) -> bool:
    haystack = " ".join(
        str(message.get(key) or "") for key in ("URI", "Contact", "ContactURI", "ContactStatusDetail")
    ).lower()
    return "transport=ws" in haystack or "transport=wss" in haystack


def _contact_status(value: str | None, *, webphone: bool = False) -> str:
    normalized = (value or "").strip().lower()
    if normalized in {"created", "reachable", "registered", "online", "lagged"}:
        return "Online"
    if normalized in {"nonqual", "nonqualified"}:
        return "Online"
    if webphone and normalized in {"unavail", "unavailable"}:
        return "Online"
    if normalized in {"removed", "unreachable", "unregistered", "rejected", "offline"}:
        return "Offline"
    return "Unknown" if normalized else ""


def _device_status(value: str | None) -> str:
    normalized = (value or "").strip().lower()
    if normalized in {"ringing"}:
        return "Ringing"
    if normalized in {"inuse", "busy", "ringinuse", "onhold"}:
        return "On Call"
    if normalized in {"not_inuse", "available"}:
        return "Online"
    if normalized in {"unavailable", "invalid", "offline"}:
        return "Offline"
    return "Unknown" if normalized else ""


def _channel_status(value: str | None) -> str:
    normalized = (value or "").strip().lower()
    if normalized in {"ring", "ringing"}:
        return "Ringing"
    if normalized in {"up", "busy"}:
        return "On Call"
    if normalized in {"down", "rsrvd", "reserved", "offhook", "dialing", "pre-ring", "prering"}:
        return "Online"
    return ""


def _status_class(status: str) -> str:
    return {
        "Online": "online",
        "On Call": "on-call",
        "Ringing": "ringing",
        "Offline": "offline",
        "Unknown": "unknown",
    }.get(status, "unknown")


live_event_hub = LiveEventHub()
