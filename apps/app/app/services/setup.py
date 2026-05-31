from __future__ import annotations

import ipaddress
import json
import os
import secrets
import socket
from datetime import UTC, datetime
from pathlib import Path
from typing import BinaryIO

import psycopg
from psycopg.rows import dict_row

from app.core.settings import get_settings
from app.models.setup import SetupWizardPayload
from app.services.auth import hash_password
from app.services.asterisk import sync_asterisk_config
from app.services.extensions import WEBPHONE_AUDIO_CODECS, WEBPHONE_TRANSPORT, WEBPHONE_VIDEO_CODECS


SETTINGS_ID = 1
MAX_CERT_UPLOAD_BYTES = 256 * 1024


def get_system_settings(connection: psycopg.Connection) -> dict:
    with connection.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT
                setup_completed, company_name, country, timezone, default_language, dialing_region,
                deployment_mode, access_mode, behind_nat, external_host, ssl_mode, ssl_contact_email,
                admin_email, sip_port, rtp_start, rtp_end, local_networks, public_base_url, caddy_enabled
            FROM system_settings
            WHERE id = %(id)s
            """,
            {"id": SETTINGS_ID},
        )
        row = cursor.fetchone()
    return dict(row) if row else _default_system_settings()


def is_setup_complete(connection: psycopg.Connection) -> bool:
    return bool(get_system_settings(connection).get("setup_completed"))


def save_ssl_settings(
    connection: psycopg.Connection,
    *,
    access_mode: str,
    ssl_mode: str,
    external_host: str,
    ssl_contact_email: str = "",
) -> dict[str, object]:
    access_mode = (access_mode or "").strip()
    ssl_mode = (ssl_mode or "").strip()
    external_host = (external_host or "").strip()
    ssl_contact_email = (ssl_contact_email or "").strip()
    if access_mode not in {"local_network", "public_domain", "public_ip", "private_self_hosted", "http_only"}:
        raise ValueError("Choose a valid access type.")
    if ssl_mode not in {"http", "public_domain", "public_ip", "internal_local", "custom_certificate"}:
        raise ValueError("Choose a valid SSL mode.")
    if access_mode == "http_only":
        ssl_mode = "http"
    if ssl_mode != "http" and not external_host:
        raise ValueError("Enter the LAN IP address or domain users will open.")
    if ssl_mode == "public_domain" and external_host and _is_ip_address(external_host):
        raise ValueError("Public domain HTTPS needs a domain name, not an IP address.")
    if ssl_mode == "public_ip" and external_host and not _is_ip_address(external_host):
        raise ValueError("Public IP HTTPS needs an IP address.")
    if ssl_mode in {"public_domain", "public_ip"} and ssl_contact_email and "@" not in ssl_contact_email:
        raise ValueError("Enter a valid email address for certificate renewal notices.")

    public_base_url = _build_public_base_url(ssl_mode, external_host)
    caddy_enabled = ssl_mode in {"public_domain", "public_ip", "internal_local", "custom_certificate"}
    with connection.cursor() as cursor:
        cursor.execute(
            """
            UPDATE system_settings
            SET access_mode = %(access_mode)s,
                external_host = %(external_host)s,
                ssl_mode = %(ssl_mode)s,
                ssl_contact_email = %(ssl_contact_email)s,
                public_base_url = %(public_base_url)s,
                caddy_enabled = %(caddy_enabled)s,
                updated_at = NOW()
            WHERE id = %(id)s
            """,
            {
                "id": SETTINGS_ID,
                "access_mode": access_mode,
                "external_host": external_host or None,
                "ssl_mode": ssl_mode,
                "ssl_contact_email": ssl_contact_email or None,
                "public_base_url": public_base_url,
                "caddy_enabled": caddy_enabled,
            },
        )
    return refresh_caddy_config(connection)


def custom_certificate_paths() -> tuple[Path, Path]:
    cert_dir = Path(get_settings().caddyfile_path).parent.parent / "certs"
    return cert_dir / "fullchain.pem", cert_dir / "privkey.pem"


def custom_certificate_ready() -> bool:
    cert_path, key_path = custom_certificate_paths()
    return cert_path.is_file() and key_path.is_file()


def save_custom_certificate_files(cert_file: BinaryIO, key_file: BinaryIO) -> None:
    cert_text = _read_certificate_upload(cert_file, "certificate")
    key_text = _read_certificate_upload(key_file, "private key")
    if "-----BEGIN CERTIFICATE-----" not in cert_text or "-----END CERTIFICATE-----" not in cert_text:
        raise ValueError("Upload a PEM certificate file that starts with BEGIN CERTIFICATE.")
    if "-----BEGIN " not in key_text or "PRIVATE KEY-----" not in key_text or "-----END " not in key_text:
        raise ValueError("Upload a PEM private key file.")

    cert_path, key_path = custom_certificate_paths()
    cert_path.parent.mkdir(parents=True, exist_ok=True)
    cert_path.write_text(cert_text.rstrip() + "\n", encoding="utf-8")
    key_path.write_text(key_text.rstrip() + "\n", encoding="utf-8")
    os.chmod(cert_path, 0o644)
    os.chmod(key_path, 0o600)


def _read_certificate_upload(file_obj: BinaryIO, label: str) -> str:
    file_obj.seek(0)
    data = file_obj.read(MAX_CERT_UPLOAD_BYTES + 1)
    if len(data) > MAX_CERT_UPLOAD_BYTES:
        raise ValueError(f"The {label} file is too large. Upload a PEM file under 256 KB.")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(f"The {label} file must be a text PEM file.") from exc
    if not text.strip():
        raise ValueError(f"Upload the {label} file.")
    return text


def refresh_caddy_config(connection: psycopg.Connection) -> dict[str, object]:
    settings_snapshot = get_system_settings(connection)
    caddyfile = render_caddyfile(settings_snapshot)
    write_caddyfile(caddyfile)
    return {
        "settings": settings_snapshot,
        "caddyfile_path": get_settings().caddyfile_path,
        "public_base_url": settings_snapshot.get("public_base_url"),
        "refreshed_at": datetime.now(UTC).isoformat(timespec="seconds"),
    }


def save_setup_wizard(connection: psycopg.Connection, payload: SetupWizardPayload) -> dict[str, object]:
    ssl_mode = payload.ssl_mode
    host = payload.external_host
    public_base_url = _build_public_base_url(ssl_mode, host)
    caddy_enabled = ssl_mode in {"public_domain", "public_ip", "internal_local", "custom_certificate"}

    if ssl_mode == "public_domain" and host and _is_ip_address(host):
        raise ValueError("Public domain HTTPS needs a domain name, not an IP address.")
    if ssl_mode == "public_ip" and host and not _is_ip_address(host):
        raise ValueError("Public IP HTTPS needs a public IP address, not a domain name.")
    if ssl_mode == "custom_certificate" and not custom_certificate_ready():
        raise ValueError("Upload the certificate and private key before using Bring Your Own Certificate.")

    with connection.cursor() as cursor:
        cursor.execute(
            """
            UPDATE system_settings
            SET
                setup_completed = TRUE,
                company_name = %(company_name)s,
                country = %(country)s,
                timezone = %(timezone)s,
                default_language = %(default_language)s,
                dialing_region = %(dialing_region)s,
                deployment_mode = %(deployment_mode)s,
                access_mode = %(access_mode)s,
                behind_nat = %(behind_nat)s,
                external_host = %(external_host)s,
                ssl_mode = %(ssl_mode)s,
                ssl_contact_email = %(ssl_contact_email)s,
                admin_email = %(admin_email)s,
                sip_port = %(sip_port)s,
                rtp_start = %(rtp_start)s,
                rtp_end = %(rtp_end)s,
                local_networks = %(local_networks)s,
                public_base_url = %(public_base_url)s,
                caddy_enabled = %(caddy_enabled)s,
                updated_at = NOW()
            WHERE id = %(id)s
            """,
            {
                "id": SETTINGS_ID,
                "company_name": payload.company_name,
                "country": payload.country,
                "timezone": payload.timezone,
                "default_language": payload.default_language,
                "dialing_region": payload.dialing_region,
                "deployment_mode": payload.deployment_mode,
                "access_mode": payload.access_mode,
                "behind_nat": payload.behind_nat,
                "external_host": host,
                "ssl_mode": ssl_mode,
                "ssl_contact_email": payload.ssl_contact_email,
                "admin_email": payload.admin_email,
                "sip_port": payload.sip_port,
                "rtp_start": payload.rtp_start,
                "rtp_end": payload.rtp_end,
                "local_networks": payload.local_networks,
                "public_base_url": public_base_url,
                "caddy_enabled": caddy_enabled,
            },
        )
        _upsert_admin_user(cursor, payload)
        _ensure_internal_secrets(cursor)
        _create_first_extension_if_needed(cursor, payload)

    sync_asterisk_config(connection, reload_config=True)
    refresh_result = refresh_caddy_config(connection)
    return {
        "settings": refresh_result["settings"],
        "caddyfile_path": refresh_result["caddyfile_path"],
    }


def render_caddyfile(system_settings: dict) -> str:
    settings = get_settings()
    ssl_mode = system_settings.get("ssl_mode") or "http"
    host = (system_settings.get("external_host") or "").strip()
    contact_email = (system_settings.get("ssl_contact_email") or "").strip()
    public_base_url = _build_public_base_url(ssl_mode, host)
    global_lines: list[str] = [
        f"  http_port {settings.public_http_port}",
        f"  https_port {settings.public_https_port}",
    ]
    if contact_email:
        global_lines.append(f"  email {contact_email}")

    if ssl_mode in {"public_domain", "public_ip"} and host:
        global_lines.append(f"  default_sni {host}")
        site_address = _https_site_address(host, settings.public_https_port)
        global_lines.append("  auto_https disable_redirects")
        return (
            "{\n"
            + "\n".join(global_lines)
            + "\n}\n\n"
            f"{site_address} {{\n"
            f"{_render_webphone_proxy_block()}"
            "  reverse_proxy app:18000\n"
            "}\n"
            + _render_http_redirect_block(host, public_base_url, settings.public_http_port)
        )

    if ssl_mode in {"internal_local", "custom_certificate"} and host:
        global_lines.append(f"  default_sni {host}")
        site_address = _https_site_address(host, settings.public_https_port)
        tls_block = "  tls internal\n" if ssl_mode == "internal_local" else "  tls /srv/omnipbx/certs/fullchain.pem /srv/omnipbx/certs/privkey.pem\n"
        global_lines.append("  auto_https disable_redirects")
        return (
            "{\n"
            + "\n".join(global_lines)
            + "\n}\n\n"
            f"{site_address} {{\n"
            f"{tls_block}"
            f"{_render_webphone_proxy_block()}"
            "  reverse_proxy app:18000\n"
            "}\n"
            + _render_http_redirect_block(host, public_base_url, settings.public_http_port)
        )

    listen_host = _http_site_address(host, settings.public_http_port)
    return (
        "{\n"
        + "\n".join(global_lines)
        + "\n}\n\n"
        f"{listen_host} {{\n"
        "  reverse_proxy app:18000\n"
        "}\n"
    )


def write_caddyfile(text: str) -> None:
    settings = get_settings()
    caddyfile = Path(settings.caddyfile_path)
    caddyfile.parent.mkdir(parents=True, exist_ok=True)
    caddyfile.write_text(text, encoding="utf-8")


def _render_webphone_proxy_block() -> str:
    return (
        "  handle /ws* {\n"
        "    reverse_proxy https://app:8089 {\n"
        "      transport http {\n"
        "        tls_insecure_skip_verify\n"
        "      }\n"
        "    }\n"
        "  }\n"
    )


def get_internal_root_ca_path() -> Path:
    return Path(get_settings().caddy_internal_root_path)


def get_environment_summary(request_host: str | None = None) -> dict[str, object]:
    settings = get_settings()
    preflight = read_host_preflight()
    host_name = socket.gethostname()
    ip_addresses = preflight.get("ip_addresses") or _detect_ip_addresses()
    default_host = (
        preflight.get("detected_host")
        or request_host
        or next((ip for ip in ip_addresses if ip not in {"127.0.0.1", "::1"}), "127.0.0.1")
    )
    return {
        "hostname": preflight.get("hostname") or host_name,
        "detected_host": default_host,
        "ip_addresses": ip_addresses,
        "internet_status": preflight.get("internet_status") or ("Online" if _internet_reachable() else "Offline or blocked"),
        "docker_ready": preflight.get("docker_ready", True),
        "firewall_status": preflight.get("firewall_status", "Unknown"),
        "firewall_name": preflight.get("firewall_name", "Not detected"),
        "selinux_status": preflight.get("selinux_status", "Unknown"),
        "apparmor_status": preflight.get("apparmor_status", "Unknown"),
        "ports": preflight.get("ports") or [
            {"label": "Setup UI", "requested": settings.http_port, "selected": settings.http_port, "status": "unknown"},
            {"label": "Public HTTP", "requested": settings.public_http_port, "selected": settings.public_http_port, "status": "unknown"},
            {"label": "Public HTTPS", "requested": settings.public_https_port, "selected": settings.public_https_port, "status": "unknown"},
            {"label": "SIP", "requested": 5060, "selected": 5060, "status": "unknown"},
            {"label": "RTP", "requested": "10000-20000", "selected": "10000-20000", "status": "unknown"},
        ],
        "recommended_mode": preflight.get(
            "recommended_mode",
            {"label": "Office or Home PBX", "value": "office", "reason": "Detected private-network style addressing."},
        ),
        "setup_url": f"http://{default_host}:{settings.http_port}/setup",
        "proxy_http_url": f"http://{default_host}:{settings.public_http_port}",
        "proxy_https_url": f"https://{default_host}:{settings.public_https_port}",
    }


def read_host_preflight() -> dict[str, object]:
    path = Path(get_settings().host_preflight_path)
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _build_public_base_url(ssl_mode: str, host: str | None) -> str | None:
    settings = get_settings()
    if not host:
        return None
    if ssl_mode in {"public_domain", "public_ip", "internal_local", "custom_certificate"}:
        port_suffix = "" if settings.public_https_port == 443 else f":{settings.public_https_port}"
        return f"https://{host}{port_suffix}"
    port_suffix = "" if settings.public_http_port == 80 else f":{settings.public_http_port}"
    return f"http://{host}{port_suffix}"


def _http_site_address(host: str | None, port: int) -> str:
    if not host:
        return f":{port}"
    if port == 80:
        return f"http://{host}"
    return f"http://{host}:{port}"


def _https_site_address(host: str, port: int) -> str:
    if port == 443:
        return host
    return f"https://{host}:{port}"


def _render_http_redirect_block(host: str, public_base_url: str | None, port: int) -> str:
    target = public_base_url or f"https://{host}"
    return (
        f"\nhttp://{host}:{port} {{\n"
        f"  redir {target}{{uri}}\n"
        "}\n"
    )


def _create_first_extension_if_needed(cursor: psycopg.Cursor, payload: SetupWizardPayload) -> None:
    extension = payload.first_extension or "10000"
    if not extension:
        return
    cursor.execute("SELECT 1 FROM extensions WHERE extension = %(extension)s", {"extension": extension})
    if cursor.fetchone():
        return
    cursor.execute(
        """
        INSERT INTO extensions (extension, display_name, secret, context, transport, codecs, video_codecs, enabled)
        VALUES (%(extension)s, %(display_name)s, %(secret)s, 'omnipbx-internal', %(transport)s, %(codecs)s, %(video_codecs)s, TRUE)
        """,
        {
            "extension": extension,
            "display_name": payload.first_extension_name or "Admin",
            "secret": payload.first_extension_secret or f"pass{extension}",
            "transport": WEBPHONE_TRANSPORT,
            "codecs": WEBPHONE_AUDIO_CODECS,
            "video_codecs": WEBPHONE_VIDEO_CODECS,
        },
    )


def _upsert_admin_user(cursor: psycopg.Cursor, payload: SetupWizardPayload) -> None:
    password_hash = hash_password(payload.admin_password)
    cursor.execute(
        """
        INSERT INTO admin_users (username, password_hash, email, role, is_owner)
        VALUES (%(username)s, %(password_hash)s, %(email)s, 'owner', TRUE)
        ON CONFLICT (username)
        DO UPDATE SET
            password_hash = EXCLUDED.password_hash,
            email = EXCLUDED.email,
            role = 'owner',
            is_owner = TRUE,
            updated_at = NOW()
        """,
        {
            "username": payload.admin_username,
            "password_hash": password_hash,
            "email": payload.admin_email,
        },
    )


def _ensure_internal_secrets(cursor: psycopg.Cursor) -> None:
    required_keys = (
        "app_secret_key",
        "service_token",
        "signing_secret",
        "ari_webhook_secret",
    )
    for key_name in required_keys:
        cursor.execute("SELECT 1 FROM internal_secrets WHERE key_name = %(key_name)s", {"key_name": key_name})
        if cursor.fetchone():
            continue
        cursor.execute(
            """
            INSERT INTO internal_secrets (key_name, secret_value)
            VALUES (%(key_name)s, %(secret_value)s)
            """,
            {"key_name": key_name, "secret_value": secrets.token_urlsafe(32)},
        )


def _is_ip_address(value: str) -> bool:
    try:
        ip = ipaddress.ip_address(value)
    except ValueError:
        return False
    return not ip.is_unspecified


def _default_system_settings() -> dict:
    return {
        "setup_completed": False,
        "company_name": "OmniPBX",
        "country": "Bangladesh",
        "timezone": "UTC",
        "default_language": "en",
        "dialing_region": "+880",
        "deployment_mode": "office",
        "access_mode": "local_network",
        "behind_nat": True,
        "external_host": None,
        "ssl_mode": "http",
        "ssl_contact_email": None,
        "admin_email": None,
        "sip_port": 5060,
        "rtp_start": 10000,
        "rtp_end": 10100,
        "local_networks": None,
        "public_base_url": None,
        "caddy_enabled": False,
    }


def _detect_ip_addresses() -> list[str]:
    addresses: set[str] = {"127.0.0.1"}
    udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        udp_socket.connect(("1.1.1.1", 80))
        addresses.add(udp_socket.getsockname()[0])
    except OSError:
        pass
    finally:
        udp_socket.close()

    try:
        for candidate in socket.gethostbyname_ex(socket.gethostname())[2]:
            if candidate and not candidate.startswith("127."):
                addresses.add(candidate)
    except OSError:
        pass

    for family in (socket.AF_INET, socket.AF_INET6):
        try:
            for result in socket.getaddrinfo(socket.gethostname(), None, family, socket.SOCK_STREAM):
                address = result[4][0]
                if address and not address.startswith("127.") and address != "::1":
                    addresses.add(address)
        except OSError:
            continue
    return sorted(addresses)


def _internet_reachable() -> bool:
    try:
        with socket.create_connection(("1.1.1.1", 53), timeout=1.5):
            return True
    except OSError:
        return False
