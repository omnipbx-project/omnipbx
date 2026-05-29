import socket
import threading
import time

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

    @property
    def version(self) -> int:
        with self._condition:
            return self._version

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
        with self._condition:
            self._version += 1
            self._last_event = event_name
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
                    self.notify(event_name)


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


live_event_hub = LiveEventHub()
