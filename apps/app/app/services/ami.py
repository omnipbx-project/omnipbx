import socket

from app.core.settings import get_settings


class AmiError(RuntimeError):
    pass


def ami_action(
    action: str,
    fields: dict[str, str] | None = None,
    *,
    timeout: float | None = None,
) -> list[dict[str, str]]:
    settings = get_settings()
    timeout_value = timeout if timeout is not None else settings.ami_timeout_seconds
    with socket.create_connection((settings.ami_host, settings.ami_port), timeout=timeout_value) as sock:
        sock.settimeout(timeout_value)
        stream = sock.makefile("rwb", buffering=0)
        _read_message(stream)
        _send_message(
            stream,
            {
                "Action": "Login",
                "Username": settings.ami_username,
                "Secret": settings.ami_password,
                "Events": "off",
            },
        )
        login_response = _read_message(stream)
        if login_response.get("Response") != "Success":
            raise AmiError(login_response.get("Message", "AMI login failed."))

        _send_message(stream, {"Action": action, **(fields or {})})
        messages = _read_until_complete(stream)
        _send_message(stream, {"Action": "Logoff"})
        return messages


def ami_command(command: str) -> str:
    messages = ami_action("Command", {"Command": command})
    output: list[str] = []
    for message in messages:
        if "Output" in message:
            output.append(message["Output"])
    return "\n".join(output)


def ami_originate_application(channel: str, application: str, data: str) -> dict[str, str]:
    messages = ami_action(
        "Originate",
        {
            "Channel": channel,
            "Application": application,
            "Data": data,
            "Async": "true",
        },
    )
    response = messages[0] if messages else {}
    if response.get("Response") not in {"Success", None}:
        raise AmiError(response.get("Message", "AMI originate failed."))
    return response


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
            if key in message:
                message[key] = f"{message[key]}\n{value.strip()}"
            else:
                message[key] = value.strip()
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
