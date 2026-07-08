from __future__ import annotations

import psycopg
from psycopg.rows import dict_row

from app.core.settings import get_settings
from app.models.softphone import SoftphoneSettingsPayload
from app.services.extensions import ADMIN_EXTENSION, WEBPHONE_TRANSPORT, get_extension


def get_softphone_settings(connection: psycopg.Connection) -> dict:
    with connection.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT
                enabled, websocket_url, sip_domain, display_name_prefix, public_host,
                stun_urls, turn_urls, turn_username, turn_credential, note
            FROM softphone_settings
            WHERE id = 1
            """
        )
        return dict(cursor.fetchone())


def save_softphone_settings(connection: psycopg.Connection, payload: SoftphoneSettingsPayload) -> dict:
    values = payload.model_dump()
    with connection.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            UPDATE softphone_settings
            SET
                enabled = %(enabled)s,
                websocket_url = %(websocket_url)s,
                sip_domain = %(sip_domain)s,
                display_name_prefix = %(display_name_prefix)s,
                public_host = %(public_host)s,
                stun_urls = %(stun_urls)s,
                turn_urls = %(turn_urls)s,
                turn_username = %(turn_username)s,
                turn_credential = %(turn_credential)s,
                note = %(note)s,
                updated_at = NOW()
            WHERE id = 1
            """
            ,
            values,
        )
    return get_softphone_settings(connection)


def set_softphone_dnd(connection: psycopg.Connection, extension: str, enabled: bool) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO softphone_extension_state (extension, dnd_enabled, updated_at)
            VALUES (%(extension)s, %(enabled)s, NOW())
            ON CONFLICT (extension) DO UPDATE
            SET dnd_enabled = EXCLUDED.dnd_enabled, updated_at = NOW()
            """,
            {"extension": extension, "enabled": enabled},
        )


def get_softphone_dnd(connection: psycopg.Connection, extension: str) -> bool:
    with connection.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            "SELECT dnd_enabled FROM softphone_extension_state WHERE extension = %(extension)s",
            {"extension": extension},
        )
        row = cursor.fetchone()
    return bool(row["dnd_enabled"]) if row else False


def build_softphone_bootstrap(connection: psycopg.Connection, extension: str, *, request_host: str = "", request_scheme: str = "https") -> dict:
    settings = get_softphone_settings(connection)
    with connection.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT extension, display_name, secret, context, transport, enabled
            FROM extensions
            WHERE extension = %(extension)s
            """,
            {"extension": extension},
        )
        row = cursor.fetchone()
    if not row:
        raise ValueError(f"Extension {extension} was not found.")
    websocket_url, sip_domain, public_host = _resolved_webphone_settings(
        settings,
        request_host=request_host,
        request_scheme=request_scheme,
    )
    webphone_allowed = bool(row["enabled"] and row.get("transport") == WEBPHONE_TRANSPORT)
    return {
        "enabled": bool(settings["enabled"] or webphone_allowed),
        "webrtc_ready": bool(webphone_allowed and websocket_url and sip_domain),
        "webphone_allowed": webphone_allowed,
        "auto_provision_enabled": webphone_allowed,
        "extension": row["extension"],
        "display_name": row["display_name"],
        "secret": row["secret"],
        "context": row["context"],
        "transport": row.get("transport"),
        "sip_domain": sip_domain,
        "websocket_url": websocket_url,
        "public_host": public_host,
        "ice_servers": ice_servers_from_settings(
            settings,
            fallback_host=_ice_host(public_host=public_host, sip_domain=sip_domain),
        ),
        "display_name_prefix": settings.get("display_name_prefix"),
        "note": settings.get("note"),
        "dnd_enabled": get_softphone_dnd(connection, row["extension"]),
    }


def resolve_current_webphone(
    connection: psycopg.Connection,
    username: str = "",
    *,
    extension: str = "",
    request_host: str = "",
    request_scheme: str = "https",
    can_switch: bool = False,
) -> dict:
    selected = (extension if can_switch else username).strip() or username.strip()
    webphone_extensions = list_webphone_extensions(connection)
    if can_switch and not selected.isdigit() and any(row["extension"] == ADMIN_EXTENSION for row in webphone_extensions):
        selected = ADMIN_EXTENSION
    if selected and not any(row["extension"] == selected for row in webphone_extensions):
        selected = ""
    if not selected and webphone_extensions and can_switch:
        selected = webphone_extensions[0]["extension"]
    if not selected:
        return {
            "available": False,
            "message": "This login does not have Webphone enabled. Ask an admin to set Phone Type to Webphone.",
            "can_switch": can_switch,
            "extensions": [{"extension": row["extension"], "display_name": row["display_name"]} for row in webphone_extensions] if can_switch else [],
            "config": None,
        }
    config = build_softphone_bootstrap(
        connection,
        selected,
        request_host=request_host,
        request_scheme=request_scheme,
    )
    return {
        "available": bool(config["webrtc_ready"]),
        "message": "Webphone ready." if config["webrtc_ready"] else "This user is not ready for Webphone.",
        "can_switch": can_switch,
        "extensions": [{"extension": row["extension"], "display_name": row["display_name"]} for row in webphone_extensions] if can_switch else [],
        "config": config,
    }


def resolve_current_desktop_softphone(
    connection: psycopg.Connection,
    username: str = "",
    *,
    extension: str = "",
    request_host: str = "",
    request_scheme: str = "https",
    can_switch: bool = False,
) -> dict:
    selected = (extension if can_switch else username).strip() or username.strip()
    if can_switch and not selected.isdigit():
        selected = ADMIN_EXTENSION
    row = get_extension(connection, selected) if selected else None
    if not row or not row.get("enabled"):
        return {
            "available": False,
            "message": "No enabled extension is available for desktop softphone provisioning.",
            "config": None,
        }

    settings = get_softphone_settings(connection)
    _, sip_domain, public_host = _resolved_webphone_settings(
        settings,
        request_host=request_host,
        request_scheme=request_scheme,
    )
    server = sip_domain or _ice_host(public_host=public_host, sip_domain=sip_domain)
    config = {
        "extension": row["extension"],
        "display_name": row["display_name"],
        "username": row["extension"],
        "auth_user": row["extension"],
        "password": row["secret"],
        "sip_domain": server,
        "server": server,
        "transport": "udp",
        "context": row.get("context"),
    }
    return {
        "available": bool(server),
        "message": "Desktop softphone settings ready." if server else "SIP domain is not configured.",
        "config": config,
    }


def list_webphone_extensions(connection: psycopg.Connection) -> list[dict]:
    with connection.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT extension, display_name
            FROM extensions
            WHERE enabled = TRUE AND transport = %(transport)s
            ORDER BY extension
            """,
            {"transport": WEBPHONE_TRANSPORT},
        )
        return [dict(row) for row in cursor.fetchall()]


def _resolved_webphone_settings(settings: dict, *, request_host: str, request_scheme: str) -> tuple[str, str, str]:
    app_settings = get_settings()
    host = (request_host or "").split(",", 1)[0].strip()
    host_no_port = host.split(":", 1)[0] if host and not host.startswith("[") else host.strip("[]")
    sip_domain = settings.get("sip_domain") or host_no_port
    websocket_url = settings.get("websocket_url")
    public_host = settings.get("public_host")
    if not websocket_url and host_no_port:
        public_port = int(app_settings.public_https_port or 443)
        websocket_host = host_no_port if public_port == 443 else f"{host_no_port}:{public_port}"
        websocket_url = f"wss://{websocket_host}/ws"
    if not public_host and host:
        public_port = int(app_settings.public_https_port or 443)
        public_host_value = host_no_port if public_port == 443 else f"{host_no_port}:{public_port}"
        public_host = f"https://{public_host_value}"
    return websocket_url or "", sip_domain or "", public_host or ""


def ice_servers_from_settings(settings: dict, *, fallback_host: str = "") -> list[dict[str, object]]:
    app_settings = get_settings()
    servers: list[dict[str, object]] = []
    stun_urls = _ice_urls(settings.get("stun_urls"))
    if stun_urls:
        servers.append({"urls": stun_urls if len(stun_urls) > 1 else stun_urls[0]})
    turn_urls = _ice_urls(settings.get("turn_urls"))
    if not turn_urls and fallback_host and app_settings.turn_credential:
        turn_urls = [f"turn:{fallback_host}:{app_settings.turn_port}"]
    if turn_urls:
        turn_server: dict[str, object] = {"urls": turn_urls if len(turn_urls) > 1 else turn_urls[0]}
        username = str(settings.get("turn_username") or app_settings.turn_username or "").strip()
        credential = str(settings.get("turn_credential") or app_settings.turn_credential or "").strip()
        if username:
            turn_server["username"] = username
        if credential:
            turn_server["credential"] = credential
        servers.append(turn_server)
    return servers


def _ice_urls(value: object) -> list[str]:
    raw_urls = str(value or "").replace(",", "\n").splitlines()
    urls: list[str] = []
    for raw_url in raw_urls:
        url = raw_url.strip()
        if not url or not url.lower().startswith(("stun:", "turn:", "turns:")):
            continue
        if url not in urls:
            urls.append(url)
    return urls


def _ice_host(*, public_host: str, sip_domain: str) -> str:
    candidate = public_host or sip_domain
    if "://" in candidate:
        candidate = candidate.split("://", 1)[1]
    return candidate.split("/", 1)[0].split(":", 1)[0].strip("[]")
