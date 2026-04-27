from __future__ import annotations

from psycopg.rows import dict_row
import psycopg

from app.services.audit import log_admin_event
from app.services.auth import authenticate_admin, get_admin_by_id, hash_password


SMTP_SETTINGS_ID = 1
SMTP_PASSWORD_SECRET_KEY = "smtp_mail_password"
ADMIN_ROLE_OWNER = "owner"
ADMIN_ROLE_ADMIN = "admin"
ADMIN_ROLE_READ_ONLY = "read_only"
ADMIN_ROLES = (ADMIN_ROLE_OWNER, ADMIN_ROLE_ADMIN, ADMIN_ROLE_READ_ONLY)


def normalize_admin_role(value: str | None, *, fallback: str = ADMIN_ROLE_ADMIN) -> str:
    role = (value or fallback).strip().lower().replace("-", "_")
    if role not in ADMIN_ROLES:
        return fallback
    return role


def role_label(role: str | None) -> str:
    normalized = normalize_admin_role(role)
    return {
        ADMIN_ROLE_OWNER: "Owner",
        ADMIN_ROLE_ADMIN: "Admin",
        ADMIN_ROLE_READ_ONLY: "Read-only",
    }[normalized]


def role_is_owner(role: str | None) -> bool:
    return normalize_admin_role(role) == ADMIN_ROLE_OWNER


def role_can_manage_admins(role: str | None) -> bool:
    return normalize_admin_role(role) == ADMIN_ROLE_OWNER


def role_can_write(role: str | None) -> bool:
    return normalize_admin_role(role) in {ADMIN_ROLE_OWNER, ADMIN_ROLE_ADMIN}


def list_admin_accounts(connection: psycopg.Connection) -> list[dict]:
    with connection.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT id, username, email, role, is_owner, created_at, updated_at
            FROM admin_users
            ORDER BY CASE role WHEN 'owner' THEN 0 WHEN 'admin' THEN 1 ELSE 2 END, username ASC
            """
        )
        rows = cursor.fetchall()
    admins = []
    for row in rows:
        admin = dict(row)
        admin["role"] = normalize_admin_role(admin.get("role"), fallback="owner" if admin.get("is_owner") else "admin")
        admin["is_owner"] = role_is_owner(admin["role"])
        admins.append(admin)
    return admins


def count_owner_admins(connection: psycopg.Connection) -> int:
    with connection.cursor() as cursor:
        cursor.execute("SELECT COUNT(*) FROM admin_users WHERE role = 'owner' OR is_owner = TRUE")
        row = cursor.fetchone()
    return int(row[0]) if row else 0


def create_admin_account(
    connection: psycopg.Connection,
    *,
    username: str,
    password: str,
    email: str | None,
    role: str = ADMIN_ROLE_ADMIN,
) -> dict:
    normalized_role = normalize_admin_role(role)
    if normalized_role == ADMIN_ROLE_OWNER and count_owner_admins(connection) <= 0:
        normalized_role = ADMIN_ROLE_OWNER
    with connection.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            INSERT INTO admin_users (username, password_hash, email, role, is_owner)
            VALUES (%(username)s, %(password_hash)s, %(email)s, %(role)s, %(is_owner)s)
            RETURNING id, username, email, role, is_owner, created_at, updated_at
            """,
            {
                "username": username,
                "password_hash": hash_password(password),
                "email": email,
                "role": normalized_role,
                "is_owner": normalized_role == ADMIN_ROLE_OWNER,
            },
        )
        row = cursor.fetchone()
    return dict(row)


def update_admin_email(connection: psycopg.Connection, admin_id: int, email: str | None) -> dict | None:
    with connection.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            UPDATE admin_users
            SET email = %(email)s,
                updated_at = NOW()
            WHERE id = %(admin_id)s
            RETURNING id, username, email, role, is_owner, created_at, updated_at
            """,
            {"admin_id": admin_id, "email": email},
        )
        row = cursor.fetchone()
    return dict(row) if row else None


def update_admin_profile(
    connection: psycopg.Connection,
    *,
    admin_id: int,
    email: str | None,
    role: str,
) -> dict | None:
    updated = update_admin_email(connection, admin_id, email)
    if not updated:
        return None
    updated = set_admin_role(connection, admin_id, role)
    return updated


def set_admin_role(connection: psycopg.Connection, admin_id: int, role: str) -> dict | None:
    admin = get_admin_by_id(connection, admin_id)
    if not admin:
        return None
    normalized_role = normalize_admin_role(role)
    if role_is_owner(admin.get("role")) and normalized_role != ADMIN_ROLE_OWNER and count_owner_admins(connection) <= 1:
        raise ValueError("At least one owner admin must remain.")
    with connection.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            UPDATE admin_users
            SET role = %(role)s,
                is_owner = %(is_owner)s,
                updated_at = NOW()
            WHERE id = %(admin_id)s
            RETURNING id, username, email, role, is_owner, created_at, updated_at
            """,
            {"admin_id": admin_id, "role": normalized_role, "is_owner": normalized_role == ADMIN_ROLE_OWNER},
        )
        row = cursor.fetchone()
    return dict(row) if row else None


def set_admin_owner_flag(connection: psycopg.Connection, admin_id: int, is_owner: bool) -> dict | None:
    return set_admin_role(connection, admin_id, ADMIN_ROLE_OWNER if is_owner else ADMIN_ROLE_ADMIN)


def delete_admin_account(
    connection: psycopg.Connection,
    *,
    admin_id: int,
    acting_admin_id: int,
) -> bool:
    admin = get_admin_by_id(connection, admin_id)
    if not admin:
        return False
    if admin_id == acting_admin_id:
        raise ValueError("You cannot delete the account you are currently using.")
    if role_is_owner(admin.get("role")) and count_owner_admins(connection) <= 1:
        raise ValueError("You cannot delete the last owner account.")
    with connection.cursor() as cursor:
        cursor.execute("DELETE FROM admin_users WHERE id = %(admin_id)s", {"admin_id": admin_id})
    return True


def change_admin_password(
    connection: psycopg.Connection,
    *,
    admin_id: int,
    new_password: str,
) -> dict | None:
    with connection.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            UPDATE admin_users
            SET password_hash = %(password_hash)s,
                updated_at = NOW()
            WHERE id = %(admin_id)s
            RETURNING id, username, email, role, is_owner, created_at, updated_at
            """,
            {"admin_id": admin_id, "password_hash": hash_password(new_password)},
        )
        row = cursor.fetchone()
    return dict(row) if row else None


def change_own_password(
    connection: psycopg.Connection,
    *,
    admin_id: int,
    current_password: str,
    new_password: str,
) -> dict:
    admin = get_admin_by_id(connection, admin_id)
    if not admin:
        raise ValueError("Admin account was not found.")
    if not authenticate_admin(connection, admin["username"], current_password):
        raise ValueError("Current password is incorrect.")
    updated = change_admin_password(connection, admin_id=admin_id, new_password=new_password)
    if not updated:
        raise ValueError("Unable to update the password for this account.")
    return updated


def get_smtp_settings(connection: psycopg.Connection) -> dict:
    with connection.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT
                id, enabled, mail_from, mail_from_name, mail_username, mail_server, mail_port,
                mail_starttls, mail_ssl_tls, use_credentials, validate_certs,
                created_at, updated_at
            FROM smtp_settings
            WHERE id = %(id)s
            """,
            {"id": SMTP_SETTINGS_ID},
        )
        row = cursor.fetchone()
        cursor.execute(
            "SELECT secret_value FROM internal_secrets WHERE key_name = %(key_name)s",
            {"key_name": SMTP_PASSWORD_SECRET_KEY},
        )
        password_row = cursor.fetchone()
    settings = dict(row) if row else {
        "id": SMTP_SETTINGS_ID,
        "enabled": False,
        "mail_from": None,
        "mail_from_name": "OmniPBX",
        "mail_username": None,
        "mail_server": None,
        "mail_port": 587,
        "mail_starttls": True,
        "mail_ssl_tls": False,
        "use_credentials": True,
        "validate_certs": True,
    }
    settings["password_configured"] = bool(password_row and password_row[0])
    return settings


def save_smtp_settings(
    connection: psycopg.Connection,
    *,
    enabled: bool,
    mail_from: str | None,
    mail_from_name: str | None,
    mail_username: str | None,
    mail_server: str | None,
    mail_port: int,
    mail_starttls: bool,
    mail_ssl_tls: bool,
    use_credentials: bool,
    validate_certs: bool,
    mail_password: str | None,
) -> dict:
    with connection.cursor(row_factory=dict_row) as cursor:
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
            RETURNING id, enabled, mail_from, mail_from_name, mail_username, mail_server, mail_port,
                      mail_starttls, mail_ssl_tls, use_credentials, validate_certs, created_at, updated_at
            """,
            {
                "id": SMTP_SETTINGS_ID,
                "enabled": enabled,
                "mail_from": mail_from,
                "mail_from_name": mail_from_name or "OmniPBX",
                "mail_username": mail_username,
                "mail_server": mail_server,
                "mail_port": mail_port,
                "mail_starttls": mail_starttls,
                "mail_ssl_tls": mail_ssl_tls,
                "use_credentials": use_credentials,
                "validate_certs": validate_certs,
            },
        )
        row = cursor.fetchone()
        if mail_password:
            cursor.execute(
                """
                INSERT INTO internal_secrets (key_name, secret_value)
                VALUES (%(key_name)s, %(secret_value)s)
                ON CONFLICT (key_name) DO UPDATE SET
                    secret_value = EXCLUDED.secret_value,
                    updated_at = NOW()
                """,
                {"key_name": SMTP_PASSWORD_SECRET_KEY, "secret_value": mail_password},
            )
        cursor.execute(
            "SELECT secret_value FROM internal_secrets WHERE key_name = %(key_name)s",
            {"key_name": SMTP_PASSWORD_SECRET_KEY},
        )
        password_row = cursor.fetchone()
    settings = dict(row)
    settings["password_configured"] = bool(password_row and password_row[0])
    return settings


def get_smtp_password(connection: psycopg.Connection) -> str | None:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT secret_value FROM internal_secrets WHERE key_name = %(key_name)s",
            {"key_name": SMTP_PASSWORD_SECRET_KEY},
        )
        row = cursor.fetchone()
    return row[0] if row else None


def add_admin_audit(
    connection: psycopg.Connection,
    *,
    event_type: str,
    actor_admin_id: int | None = None,
    actor_username: str | None = None,
    target_kind: str | None = None,
    target_value: str | None = None,
    message: str | None = None,
    details: dict | None = None,
) -> None:
    log_admin_event(
        connection,
        event_type=event_type,
        actor_admin_id=actor_admin_id,
        actor_username=actor_username,
        target_kind=target_kind,
        target_value=target_value,
        message=message,
        details=details,
    )
