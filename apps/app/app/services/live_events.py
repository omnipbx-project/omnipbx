import socket
import threading
import time
from copy import deepcopy
from collections.abc import Callable
from datetime import UTC, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.core.settings import get_settings
from app.services.api_push import dispatch_realtime_call_event
from app.services.setup import get_system_settings


INTERESTING_EVENTS = {
    "BridgeCreate",
    "BridgeDestroy",
    "BridgeEnter",
    "BridgeLeave",
    "ContactStatus",
    "DeviceStateChange",
    "DialBegin",
    "DialEnd",
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
        self._sent_call_events: dict[str, float] = {}
        self._call_sessions: dict[str, dict[str, str]] = {}

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
        self._dispatch_call_webhook(event_name, message)
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
            _send_message(
                stream,
                {
                    "Action": "Login",
                    "Username": settings.ami_username,
                    "Secret": settings.ami_password,
                    "Events": "on",
                },
            )
            response = _read_next_message(stream)
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

    def _dispatch_call_webhook(self, event_name: str, message: dict[str, str]) -> None:
        event = _call_webhook_payload(event_name, message)
        if not event:
            return
        now = time.time()
        with self._condition:
            self._sent_call_events = {
                key: seen_at
                for key, seen_at in self._sent_call_events.items()
                if now - seen_at < 600
            }
            self._call_sessions = {
                key: session
                for key, session in self._call_sessions.items()
                if now - float(session.get("_seen_at", "0")) < 900
            }
            event = self._normalize_call_event(event, now)
            event_id = str(event["event_id"])
            if event_id in self._sent_call_events:
                return
            self._sent_call_events[event_id] = now
        dispatch_realtime_call_event(_with_local_timestamp(event))

    def _normalize_call_event(self, event: dict[str, object], seen_at: float) -> dict[str, object]:
        linkedid = str(event.get("linkedid") or event.get("uniqueid") or "")
        if not linkedid:
            return event

        session = self._call_sessions.get(linkedid, {})
        event_name = str(event.get("event") or "")
        event_time = str(event.get("timestamp") or datetime.now(UTC).isoformat())
        session = self._update_call_timeline(session, event_name, event_time)
        if event.get("event") in {"call.dialing", "call.ringing"} and event.get("direction") != "unknown":
            session = {
                **session,
                "direction": str(event.get("direction") or ""),
                "caller": str(event.get("caller") or ""),
                "callee": str(event.get("callee") or ""),
                "agent_extension": str(event.get("agent_extension") or ""),
                "trunk": str(event.get("trunk") or ""),
                "_seen_at": str(seen_at),
            }
            self._call_sessions[linkedid] = session
            return _apply_call_summary(event, session)

        if session:
            for key in ("direction", "caller", "callee", "agent_extension", "trunk"):
                if session.get(key):
                    event[key] = session[key]
            session["_seen_at"] = str(seen_at)
            self._call_sessions[linkedid] = session
        return _apply_call_summary(event, session)

    def _update_call_timeline(self, session: dict[str, str], event_name: str, event_time: str) -> dict[str, str]:
        updated = dict(session)
        if event_name in {"call.dialing", "call.ringing"}:
            updated.setdefault("call_started_at", event_time)
        elif event_name == "call.answered":
            updated.setdefault("call_started_at", event_time)
            updated.setdefault("call_answered_at", event_time)
        elif event_name in {"call.hangup", "call.dial_ended"}:
            updated.setdefault("call_started_at", event_time)
            if event_name == "call.hangup":
                updated["call_ended_at"] = event_time
        return updated


def _send_message(stream, fields: dict[str, str]) -> None:
    payload = "".join(f"{key}: {value}\r\n" for key, value in fields.items()) + "\r\n"
    stream.write(payload.encode("utf-8"))


def _read_message(stream) -> dict[str, str]:
    message: dict[str, str] = {}
    while True:
        raw_line = stream.readline()
        if not raw_line:
            if not message:
                raise EOFError("AMI event connection closed.")
            break
        line = raw_line.decode("utf-8", errors="replace").rstrip("\r\n")
        if not line:
            break
        key, separator, value = line.partition(":")
        if separator:
            message[key] = value.strip()
    return message


def _read_next_message(stream) -> dict[str, str]:
    while True:
        message = _read_message(stream)
        if message:
            return message


def _call_webhook_payload(event_name: str, message: dict[str, str]) -> dict[str, object] | None:
    event_type = _call_event_type(event_name, message)
    if not event_type:
        return None
    channel = message.get("Channel", "")
    dest_channel = message.get("DestChannel", "")
    uniqueid = message.get("Uniqueid") or message.get("DestUniqueid") or ""
    linkedid = message.get("Linkedid") or uniqueid
    direction = _call_direction(message)
    caller = _caller_number(message, direction)
    callee = _callee_number(message, direction)
    agent_extension = _agent_extension(message, direction)
    trunk = _trunk_name(message)
    status = event_type.rsplit(".", 1)[-1]
    call_key = linkedid or uniqueid or channel or dest_channel
    return {
        "event": event_type,
        "event_id": "|".join([event_type, call_key]),
        "ami_event": event_name,
        "direction": direction,
        "caller": caller,
        "callee": callee,
        "agent_extension": agent_extension,
        "trunk": trunk,
        "uniqueid": uniqueid,
        "linkedid": linkedid,
        "channel": channel,
        "dest_channel": dest_channel,
        "status": status,
        "dial_status": message.get("DialStatus", ""),
        "hangup_cause": message.get("Cause", ""),
        "hangup_cause_text": message.get("Cause-txt", ""),
        "timestamp": datetime.now(UTC).isoformat(),
    }


def _with_local_timestamp(event: dict[str, object]) -> dict[str, object]:
    timezone_name = "UTC"
    try:
        import psycopg

        settings = get_settings()
        with psycopg.connect(settings.db_dsn, autocommit=True) as connection:
            timezone_name = str(get_system_settings(connection).get("timezone") or "UTC")
    except Exception:
        timezone_name = "UTC"

    try:
        local_tz = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        local_tz = ZoneInfo("UTC")
        timezone_name = "UTC"

    enriched = dict(event)
    event_time = _event_datetime(event)
    enriched["timezone"] = timezone_name
    enriched["local_timestamp"] = event_time.astimezone(local_tz).isoformat()
    for source_key, target_key in (
        ("call_started_at", "call_started_local_at"),
        ("call_answered_at", "call_answered_local_at"),
        ("call_ended_at", "call_ended_local_at"),
    ):
        value = str(enriched.get(source_key) or "")
        if not value:
            continue
        try:
            enriched[target_key] = datetime.fromisoformat(value).astimezone(local_tz).isoformat()
        except ValueError:
            continue
    return enriched


def _apply_call_summary(event: dict[str, object], session: dict[str, str]) -> dict[str, object]:
    if not session:
        return event
    enriched = dict(event)
    for key in ("call_started_at", "call_answered_at", "call_ended_at"):
        if session.get(key):
            enriched[key] = session[key]

    started_at = _parse_iso_datetime(str(session.get("call_started_at") or ""))
    answered_at = _parse_iso_datetime(str(session.get("call_answered_at") or ""))
    ended_at = _parse_iso_datetime(str(session.get("call_ended_at") or "")) or _event_datetime(event)
    if started_at:
        enriched["duration_seconds"] = max(0, int((ended_at - started_at).total_seconds()))
    if answered_at:
        enriched["talk_seconds"] = max(0, int((ended_at - answered_at).total_seconds()))
    else:
        enriched["talk_seconds"] = 0
    enriched["call_result"] = _call_result(enriched)
    return enriched


def _event_datetime(event: dict[str, object]) -> datetime:
    timestamp = str(event.get("timestamp") or "")
    if timestamp:
        try:
            return datetime.fromisoformat(timestamp).astimezone(UTC)
        except ValueError:
            pass
    return datetime.now(UTC)


def _parse_iso_datetime(value: str) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value).astimezone(UTC)
    except ValueError:
        return None


def _call_result(event: dict[str, object]) -> str:
    if event.get("call_answered_at"):
        return "answered"
    dial_status = str(event.get("dial_status") or "").upper()
    hangup_cause = str(event.get("hangup_cause") or "")
    if dial_status in {"NOANSWER", "CANCEL"} or hangup_cause in {"19", "26"}:
        return "missed"
    if dial_status in {"BUSY", "CHANUNAVAIL", "CONGESTION"}:
        return "failed"
    if str(event.get("event") or "") == "call.hangup":
        return "ended"
    return "in_progress"


def _call_event_type(event_name: str, message: dict[str, str]) -> str:
    if event_name == "DialBegin":
        return "call.ringing" if _call_direction(message) == "inbound" else "call.dialing"
    if event_name == "BridgeEnter":
        return "call.answered"
    if event_name == "DialEnd":
        return "call.dial_ended"
    if event_name == "Hangup":
        return "call.hangup"
    return ""


def _call_direction(message: dict[str, str]) -> str:
    context = (message.get("Context") or message.get("DestContext") or "").lower()
    channel = message.get("Channel", "")
    dest_channel = message.get("DestChannel", "")
    if "from-trunk" in context or (_is_trunk_channel(channel) and _is_extension_channel(dest_channel)):
        return "inbound"
    if "from-internal-trunks" in context or (_is_extension_channel(channel) and (_is_trunk_channel(dest_channel) or message.get("DialString"))):
        return "outbound"
    if _is_extension_channel(channel) and _is_extension_channel(dest_channel):
        return "internal"
    return "unknown"


def _caller_number(message: dict[str, str], direction: str) -> str:
    if direction == "outbound":
        return _first_present(message, "CallerIDNum", "ConnectedLineNum")
    if direction == "inbound":
        return _first_present(message, "CallerIDNum", "ConnectedLineNum")
    return _first_present(message, "CallerIDNum", "ConnectedLineNum", "DestCallerIDNum")


def _callee_number(message: dict[str, str], direction: str) -> str:
    if direction == "outbound":
        return _dialed_number(message)
    if direction == "inbound":
        return _extension_from_channel(message.get("DestChannel", "")) or _first_present(message, "Exten", "DestExten", "ConnectedLineNum")
    return _dialed_number(message) or _first_present(message, "Exten", "DestExten", "DestCallerIDNum")


def _agent_extension(message: dict[str, str], direction: str) -> str:
    if direction == "outbound":
        return _extension_from_channel(message.get("Channel", "")) or _first_present(message, "CallerIDNum")
    if direction == "inbound":
        return _extension_from_channel(message.get("DestChannel", "")) or _first_present(message, "DestCallerIDNum", "ConnectedLineNum")
    return _extension_from_channel(message.get("Channel", "")) or _extension_from_channel(message.get("DestChannel", ""))


def _trunk_name(message: dict[str, str]) -> str:
    for channel in (message.get("Channel", ""), message.get("DestChannel", "")):
        if _is_trunk_channel(channel):
            return _channel_resource(channel)
    dial_string = message.get("DialString", "")
    if "@" in dial_string:
        return dial_string.rsplit("@", 1)[-1].split("/", 1)[0].strip()
    return ""


def _dialed_number(message: dict[str, str]) -> str:
    exten = _first_present(message, "Exten", "DestExten")
    if exten and exten.lower() != "s":
        return exten
    dial_string = message.get("DialString", "")
    if dial_string:
        value = dial_string.split("@", 1)[0].rsplit("/", 1)[-1].strip()
        if value and not value.startswith("PJSIP"):
            return value
    return _first_present(message, "DestCallerIDNum", "ConnectedLineNum")


def _first_present(message: dict[str, str], *keys: str) -> str:
    for key in keys:
        value = str(message.get(key) or "").strip()
        if value and value != "<unknown>":
            return value
    return ""


def _is_extension_channel(channel: str) -> bool:
    return _extension_from_channel(channel) != ""


def _is_trunk_channel(channel: str) -> bool:
    resource = _channel_resource(channel)
    return bool(resource and not resource.isdigit())


def _extension_from_channel(channel: str) -> str:
    resource = _channel_resource(channel)
    return resource if resource.isdigit() else ""


def _channel_resource(channel: str) -> str:
    value = (channel or "").strip()
    if "/" in value:
        value = value.split("/", 1)[1]
    return value.split(";", 1)[0].split("@", 1)[0].split("-", 1)[0].strip()


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
