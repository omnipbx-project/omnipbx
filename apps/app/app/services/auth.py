from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from datetime import UTC, datetime, timedelta

import psycopg
from psycopg.rows import dict_row


AUTH_COOKIE_NAME = "omnipbx_session"
SESSION_TTL_SECONDS = 60 * 60 * 12
PASSWORD_RESET_TTL_MINUTES = 30
ROLE_OWNER = "owner"
ROLE_ADMIN = "admin"
ROLE_READ_ONLY = "read_only"


def authenticate_admin(connection: psycopg.Connection, username: str, password: str) -> dict | None:
    with connection.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT id, username, password_hash, email, role, is_owner
            FROM admin_users
            WHERE username = %(username)s
            """,
            {"username": username},
        )
        admin = cursor.fetchone()
    if not admin:
        return None
    if not verify_password(password, admin["password_hash"]):
        return None
    return dict(admin)


def get_admin_by_id(connection: psycopg.Connection, admin_id: int) -> dict | None:
    with connection.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT id, username, password_hash, email, role, is_owner
            FROM admin_users
            WHERE id = %(admin_id)s
            """,
            {"admin_id": admin_id},
        )
        admin = cursor.fetchone()
    return dict(admin) if admin else None


def has_admin_users(connection: psycopg.Connection) -> bool:
    with connection.cursor() as cursor:
        cursor.execute("SELECT EXISTS (SELECT 1 FROM admin_users)")
        row = cursor.fetchone()
    return bool(row[0]) if row else False


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=2**14, r=8, p=1)
    encoded_salt = base64.b64encode(salt).decode("ascii")
    encoded_digest = base64.b64encode(digest).decode("ascii")
    return f"scrypt${encoded_salt}${encoded_digest}"


def verify_password(password: str, password_hash: str) -> bool:
    try:
        algorithm, encoded_salt, encoded_digest = password_hash.split("$", 2)
    except ValueError:
        return False
    if algorithm != "scrypt":
        return False
    salt = base64.b64decode(encoded_salt.encode("ascii"))
    expected = base64.b64decode(encoded_digest.encode("ascii"))
    actual = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=2**14, r=8, p=1)
    return hmac.compare_digest(actual, expected)


def issue_session_cookie(connection: psycopg.Connection, admin: dict) -> str:
    secret = _get_or_create_secret(connection, "app_secret_key")
    now = int(time.time())
    payload = {
        "admin_id": admin["id"],
        "username": admin["username"],
        "role": admin.get("role") or ("owner" if admin.get("is_owner") else "admin"),
        "issued_at": now,
        "expires_at": now + SESSION_TTL_SECONDS,
        "password_marker": _password_marker(admin["password_hash"]),
    }
    payload_bytes = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    payload_encoded = base64.urlsafe_b64encode(payload_bytes).decode("ascii").rstrip("=")
    signature = hmac.new(secret.encode("utf-8"), payload_encoded.encode("utf-8"), hashlib.sha256).digest()
    signature_encoded = base64.urlsafe_b64encode(signature).decode("ascii").rstrip("=")
    return f"{payload_encoded}.{signature_encoded}"


def resolve_session(connection: psycopg.Connection, cookie_value: str | None) -> dict | None:
    if not cookie_value or "." not in cookie_value:
        return None

    payload_encoded, signature_encoded = cookie_value.split(".", 1)
    secret = _get_or_create_secret(connection, "app_secret_key")
    expected_signature = hmac.new(secret.encode("utf-8"), payload_encoded.encode("utf-8"), hashlib.sha256).digest()
    expected_signature_encoded = base64.urlsafe_b64encode(expected_signature).decode("ascii").rstrip("=")
    if not hmac.compare_digest(signature_encoded, expected_signature_encoded):
        return None

    try:
        payload = json.loads(_urlsafe_b64decode(payload_encoded).decode("utf-8"))
    except (ValueError, json.JSONDecodeError):
        return None

    if int(payload.get("expires_at", 0)) < int(time.time()):
        return None

    admin = get_admin_by_id(connection, int(payload.get("admin_id", 0)))
    if not admin:
        return None
    if payload.get("password_marker") != _password_marker(admin["password_hash"]):
        return None
    if payload.get("role") != (admin.get("role") or ("owner" if admin.get("is_owner") else "admin")):
        return None
    return admin


def clear_session_cookie(response) -> None:
    response.delete_cookie(AUTH_COOKIE_NAME, path="/")


def _get_or_create_secret(connection: psycopg.Connection, key_name: str) -> str:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT secret_value FROM internal_secrets WHERE key_name = %(key_name)s",
            {"key_name": key_name},
        )
        row = cursor.fetchone()
        if row:
            return row[0]

        secret_value = secrets.token_urlsafe(32)
        cursor.execute(
            """
            INSERT INTO internal_secrets (key_name, secret_value)
            VALUES (%(key_name)s, %(secret_value)s)
            ON CONFLICT (key_name) DO UPDATE SET
                secret_value = internal_secrets.secret_value,
                updated_at = NOW()
            RETURNING secret_value
            """,
            {"key_name": key_name, "secret_value": secret_value},
        )
        created_row = cursor.fetchone()
    return created_row[0]


def _password_marker(password_hash: str) -> str:
    return hashlib.sha256(password_hash.encode("utf-8")).hexdigest()[:20]


def _urlsafe_b64decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def generate_password_reset_token(
    connection: psycopg.Connection,
    admin_user_id: int,
    requested_ip: str | None = None,
) -> str:
    raw_token = secrets.token_urlsafe(32)
    token_hash = _hash_reset_token(raw_token)
    expires_at = datetime.now(UTC) + timedelta(minutes=PASSWORD_RESET_TTL_MINUTES)
    with connection.cursor() as cursor:
        cursor.execute(
            """
            UPDATE password_reset_tokens
            SET used_at = NOW()
            WHERE admin_user_id = %(admin_user_id)s
              AND used_at IS NULL
              AND expires_at > NOW()
            """,
            {"admin_user_id": admin_user_id},
        )
        cursor.execute(
            """
            INSERT INTO password_reset_tokens (admin_user_id, token_hash, requested_ip, expires_at)
            VALUES (%(admin_user_id)s, %(token_hash)s, %(requested_ip)s, %(expires_at)s)
            """,
            {
                "admin_user_id": admin_user_id,
                "token_hash": token_hash,
                "requested_ip": requested_ip,
                "expires_at": expires_at,
            },
        )
    return raw_token


def get_reset_token_record(connection: psycopg.Connection, raw_token: str) -> dict | None:
    token_hash = _hash_reset_token(raw_token)
    with connection.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT
                prt.id,
                prt.admin_user_id,
                prt.expires_at,
                prt.used_at,
                au.username,
                au.email
            FROM password_reset_tokens prt
            JOIN admin_users au ON au.id = prt.admin_user_id
            WHERE prt.token_hash = %(token_hash)s
            """,
            {"token_hash": token_hash},
        )
        row = cursor.fetchone()
    return dict(row) if row else None


def is_reset_token_usable(record: dict | None) -> bool:
    if not record:
        return False
    if record.get("used_at") is not None:
        return False
    expires_at = record.get("expires_at")
    if not expires_at:
        return False
    return expires_at > datetime.now(UTC)


def consume_password_reset_token(
    connection: psycopg.Connection,
    raw_token: str,
    new_password: str,
) -> dict | None:
    record = get_reset_token_record(connection, raw_token)
    if not is_reset_token_usable(record):
        return None
    password_hash = hash_password(new_password)
    with connection.cursor() as cursor:
        cursor.execute(
            """
            UPDATE admin_users
            SET password_hash = %(password_hash)s,
                updated_at = NOW()
            WHERE id = %(admin_user_id)s
            """,
            {"password_hash": password_hash, "admin_user_id": record["admin_user_id"]},
        )
        cursor.execute(
            """
            UPDATE password_reset_tokens
            SET used_at = NOW()
            WHERE token_hash = %(token_hash)s
            """,
            {"token_hash": _hash_reset_token(raw_token)},
        )
    return get_admin_by_id(connection, int(record["admin_user_id"]))


def _hash_reset_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
