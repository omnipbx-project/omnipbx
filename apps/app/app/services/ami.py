import socket
import threading

from app.core.settings import get_settings


class AmiError(RuntimeError):
    pass


class _PersistentAmiSession:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._sock: socket.socket | None = None
        self._stream = None

    def action(
        self,
        action: str,
        fields: dict[str, str] | None = None,
        *,
        timeout: float | None = None,
    ) -> list[dict[str, str]]:
        with self._lock:
            try:
                self._connect(timeout=timeout)
                assert self._stream is not None
                _send_message(self._stream, {"Action": action, **(fields or {})})
                return _read_until_complete(self._stream)
            except Exception:
                self.close()
                raise

    def close(self) -> None:
        stream = self._stream
        sock = self._sock
        self._stream = None
        self._sock = None
        if stream is not None:
            try:
                stream.close()
            except OSError:
                pass
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass

    def _connect(self, *, timeout: float | None) -> None:
        if self._sock is not None and self._stream is not None:
            if timeout is not None:
                self._sock.settimeout(timeout)
            return

        settings = get_settings()
        timeout_value = timeout if timeout is not None else settings.ami_timeout_seconds
        sock = socket.create_connection((settings.ami_host, settings.ami_port), timeout=timeout_value)
        sock.settimeout(timeout_value)
        stream = sock.makefile("rwb", buffering=0)
        try:
            _send_message(
                stream,
                {
                    "Action": "Login",
                    "Username": settings.ami_username,
                    "Secret": settings.ami_password,
                    "Events": "off",
                },
            )
            login_response = _read_next_message(stream)
            if login_response.get("Response") != "Success":
                raise AmiError(login_response.get("Message", "AMI login failed."))
        except Exception:
            try:
                stream.close()
            finally:
                sock.close()
            raise

        self._sock = sock
        self._stream = stream


_AMI_SESSION = _PersistentAmiSession()


def ami_action(
    action: str,
    fields: dict[str, str] | None = None,
    *,
    timeout: float | None = None,
) -> list[dict[str, str]]:
    return _AMI_SESSION.action(action, fields, timeout=timeout)


def ami_command(command: str) -> str:
    messages = ami_action("Command", {"Command": command})
    output: list[str] = []
    for message in messages:
        if "Output" in message:
            output.append(message["Output"])
    return "\n".join(output)


def ami_originate_application(
    channel: str,
    application: str,
    data: str,
    *,
    caller_id: str = "",
    variables: dict[str, str] | None = None,
) -> dict[str, str]:
    fields = {
        "Channel": channel,
        "Application": application,
        "Data": data,
        "Async": "true",
    }
    if caller_id:
        fields["CallerID"] = caller_id
    if variables:
        fields["Variable"] = [f"{key}={value}" for key, value in variables.items()]
    messages = ami_action(
        "Originate",
        fields,
    )
    response = messages[0] if messages else {}
    if response.get("Response") not in {"Success", None}:
        raise AmiError(response.get("Message", "AMI originate failed."))
    return response


def ami_originate_extension(channel: str, context: str, extension: str, *, caller_id: str = "") -> dict[str, str]:
    fields = {
        "Channel": channel,
        "Context": context,
        "Exten": extension,
        "Priority": "1",
        "Async": "true",
    }
    if caller_id:
        fields["CallerID"] = caller_id
    messages = ami_action("Originate", fields)
    response = messages[0] if messages else {}
    if response.get("Response") not in {"Success", None}:
        raise AmiError(response.get("Message", "AMI originate failed."))
    return response


def _send_message(stream, fields: dict[str, str | list[str]]) -> None:
    lines: list[str] = []
    for key, value in fields.items():
        values = value if isinstance(value, list) else [value]
        lines.extend(f"{key}: {item}\r\n" for item in values)
    payload = "".join(lines) + "\r\n"
    stream.write(payload.encode("utf-8"))


def _read_message(stream) -> dict[str, str]:
    message: dict[str, str] = {}
    while True:
        raw_line = stream.readline()
        if not raw_line:
            if not message:
                raise EOFError("AMI connection closed.")
            break
        line = raw_line.decode("utf-8", errors="replace").rstrip("\r\n")
        if not line:
            break
        key, separator, value = line.partition(":")
        if separator:
            if key in message:
                message[key] = f"{message[key]}\n{value.strip()}"
            else:
                message[key] = value.strip()
    return message


def _read_next_message(stream) -> dict[str, str]:
    while True:
        message = _read_message(stream)
        if message:
            return message


def _read_until_complete(stream) -> list[dict[str, str]]:
    messages: list[dict[str, str]] = []
    while True:
        message = _read_message(stream)
        if not message:
            break
        messages.append(message)
        if _is_complete(message):
            break
    return messages


def _is_complete(message: dict[str, str]) -> bool:
    event = message.get("Event", "")
    response = message.get("Response", "")
    if event.endswith("Complete") or event in {"CommandComplete", "OriginateResponse"}:
        return True
    return response in {"Success", "Error", "Follows"}
