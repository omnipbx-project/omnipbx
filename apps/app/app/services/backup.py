from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from psycopg.rows import dict_row
import psycopg

from app.core.settings import get_settings
from app.services.admin_accounts import normalize_admin_role


BACKUP_VERSION = 1


def get_backup_dir() -> Path:
    path = Path(get_settings().runtime_dir) / "backups"
    path.mkdir(parents=True, exist_ok=True)
    return path


def list_backup_files() -> list[dict]:
    backup_dir = get_backup_dir()
    files = sorted(backup_dir.glob("*.json"), key=lambda item: item.stat().st_mtime, reverse=True)
    snapshots: list[dict] = []
    for file_path in files:
        try:
            stat = file_path.stat()
            with file_path.open("r", encoding="utf-8") as fh:
                payload = json.load(fh)
        except Exception:
            continue
        snapshots.append(
            {
                "file_name": file_path.name,
                "path": str(file_path),
                "label": payload.get("label") or file_path.stem,
                "version": payload.get("version", BACKUP_VERSION),
                "exported_at": payload.get("exported_at"),
                "size_bytes": stat.st_size,
            }
        )
    return snapshots


def create_backup_bundle(connection: psycopg.Connection, *, label: str, actor_username: str | None = None) -> Path:
    backup_dir = get_backup_dir()
    timestamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    safe_label = _slugify(label) if label else "omnipbx"
    file_path = backup_dir / f"omnipbx-backup-{timestamp}-{safe_label}.json"
    payload = {
        "version": BACKUP_VERSION,
        "label": label or "OmniPBX backup",
        "exported_at": datetime.now(UTC).isoformat(),
        "exported_by": actor_username,
        "system_settings": _fetch_one(connection, "SELECT * FROM system_settings WHERE id = 1"),
        "admin_users": _fetch_all(connection, "SELECT id, username, password_hash, email, role, is_owner, created_at, updated_at FROM admin_users ORDER BY id"),
        "smtp_settings": _fetch_one(connection, "SELECT * FROM smtp_settings WHERE id = 1"),
        "internal_secrets": _fetch_all(connection, "SELECT key_name, secret_value, created_at, updated_at FROM internal_secrets ORDER BY key_name"),
    }
    with file_path.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, sort_keys=True, default=_json_default)
    return file_path


def restore_backup_bundle(connection: psycopg.Connection, backup_payload: dict) -> None:
    if int(backup_payload.get("version", 0)) != BACKUP_VERSION:
        raise ValueError("Unsupported backup version.")

    system_settings = backup_payload.get("system_settings") or {}
    admin_users = backup_payload.get("admin_users") or []
    smtp_settings = backup_payload.get("smtp_settings") or {}
    internal_secrets = backup_payload.get("internal_secrets") or []

    with connection.cursor() as cursor:
        if system_settings:
            cursor.execute(
                """
                INSERT INTO system_settings (
                    id, setup_completed, company_name, country, timezone, default_language, dialing_region,
                    deployment_mode, access_mode, behind_nat, external_host, ssl_mode, ssl_contact_email, admin_email,
                    sip_port, rtp_start, rtp_end, local_networks, public_base_url, caddy_enabled
                )
                VALUES (
                    %(id)s, %(setup_completed)s, %(company_name)s, %(country)s, %(timezone)s, %(default_language)s, %(dialing_region)s,
                    %(deployment_mode)s, %(access_mode)s, %(behind_nat)s, %(external_host)s, %(ssl_mode)s, %(ssl_contact_email)s, %(admin_email)s,
                    %(sip_port)s, %(rtp_start)s, %(rtp_end)s, %(local_networks)s, %(public_base_url)s, %(caddy_enabled)s
                )
                ON CONFLICT (id) DO UPDATE SET
                    setup_completed = EXCLUDED.setup_completed,
                    company_name = EXCLUDED.company_name,
                    country = EXCLUDED.country,
                    timezone = EXCLUDED.timezone,
                    default_language = EXCLUDED.default_language,
                    dialing_region = EXCLUDED.dialing_region,
                    deployment_mode = EXCLUDED.deployment_mode,
                    access_mode = EXCLUDED.access_mode,
                    behind_nat = EXCLUDED.behind_nat,
                    external_host = EXCLUDED.external_host,
                    ssl_mode = EXCLUDED.ssl_mode,
                    ssl_contact_email = EXCLUDED.ssl_contact_email,
                    admin_email = EXCLUDED.admin_email,
                    sip_port = EXCLUDED.sip_port,
                    rtp_start = EXCLUDED.rtp_start,
                    rtp_end = EXCLUDED.rtp_end,
                    local_networks = EXCLUDED.local_networks,
                    public_base_url = EXCLUDED.public_base_url,
                    caddy_enabled = EXCLUDED.caddy_enabled,
                    updated_at = NOW()
                """,
                {**system_settings, "id": 1},
            )

        if smtp_settings:
            cursor.execute(
                """
                INSERT INTO smtp_settings (
                    id, enabled, mail_from, mail_from_name, mail_username, mail_server, mail_port,
                    mail_starttls, mail_ssl_tls, use_credentials, validate_certs
                )
                VALUES (
                    %(id)s, %(enabled)s, %(mail_from)s, %(mail_from_name)s, %(mail_username)s, %(mail_server)s, %(mail_port)s,
                    %(mail_starttls)s, %(mail_ssl_tls)s, %(use_credentials)s, %(validate_certs)s
                )
                ON CONFLICT (id) DO UPDATE SET
                    enabled = EXCLUDED.enabled,
                    mail_from = EXCLUDED.mail_from,
                    mail_from_name = EXCLUDED.mail_from_name,
                    mail_username = EXCLUDED.mail_username,
                    mail_server = EXCLUDED.mail_server,
                    mail_port = EXCLUDED.mail_port,
                    mail_starttls = EXCLUDED.mail_starttls,
                    mail_ssl_tls = EXCLUDED.mail_ssl_tls,
                    use_credentials = EXCLUDED.use_credentials,
                    validate_certs = EXCLUDED.validate_certs,
                    updated_at = NOW()
                """,
                {**smtp_settings, "id": 1},
            )

        for admin in admin_users:
            role = normalize_admin_role(admin.get("role"), fallback="owner" if admin.get("is_owner") else "admin")
            cursor.execute(
                """
                INSERT INTO admin_users (username, password_hash, email, role, is_owner, created_at, updated_at)
                VALUES (%(username)s, %(password_hash)s, %(email)s, %(role)s, %(is_owner)s, COALESCE(%(created_at)s, NOW()), COALESCE(%(updated_at)s, NOW()))
                ON CONFLICT (username) DO UPDATE SET
                    password_hash = EXCLUDED.password_hash,
                    email = EXCLUDED.email,
                    role = EXCLUDED.role,
                    is_owner = EXCLUDED.is_owner,
                    updated_at = NOW()
                """,
                {
                    **admin,
                    "role": role,
                    "is_owner": role == "owner",
                },
            )

        for secret in internal_secrets:
            cursor.execute(
                """
                INSERT INTO internal_secrets (key_name, secret_value)
                VALUES (%(key_name)s, %(secret_value)s)
                ON CONFLICT (key_name) DO UPDATE SET
                    secret_value = EXCLUDED.secret_value,
                    updated_at = NOW()
                """,
                secret,
            )


def load_backup_payload(file_path: Path) -> dict:
    with file_path.open("r", encoding="utf-8") as fh:
        payload = json.load(fh)
    if not isinstance(payload, dict):
        raise ValueError("Invalid backup file.")
    return payload


def _fetch_one(connection: psycopg.Connection, query: str) -> dict | None:
    with connection.cursor(row_factory=dict_row) as cursor:
        cursor.execute(query)
        row = cursor.fetchone()
    return dict(row) if row else None


def _fetch_all(connection: psycopg.Connection, query: str) -> list[dict]:
    with connection.cursor(row_factory=dict_row) as cursor:
        cursor.execute(query)
        rows = cursor.fetchall()
    return [dict(row) for row in rows]


def _slugify(value: str) -> str:
    cleaned = []
    for char in value.lower():
        if char.isalnum():
            cleaned.append(char)
        elif cleaned and cleaned[-1] != "-":
            cleaned.append("-")
    slug = "".join(cleaned).strip("-")
    return slug[:40] or "omnipbx"


def _json_default(value):
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat()
    return str(value)
