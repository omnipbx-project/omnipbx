from __future__ import annotations

from pathlib import Path

from fastapi_mail import ConnectionConfig, FastMail, MessageSchema, MessageType
import psycopg

from app.core.settings import get_settings
from app.services.admin_accounts import get_smtp_password, get_smtp_settings


EMAIL_TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "templates" / "email"


def smtp_is_ready(smtp_settings: dict) -> bool:
    if not smtp_settings.get("enabled"):
        return False
    if not smtp_settings.get("mail_from") or not smtp_settings.get("mail_server") or not smtp_settings.get("mail_port"):
        return False
    if smtp_settings.get("use_credentials") and not smtp_settings.get("password_configured"):
        return False
    return True


def build_mail_config(connection: psycopg.Connection) -> ConnectionConfig | None:
    smtp_settings = get_smtp_settings(connection)
    if not smtp_is_ready(smtp_settings):
        return None
    mail_password = get_smtp_password(connection) or ""
    return ConnectionConfig(
        MAIL_USERNAME=smtp_settings.get("mail_username") or smtp_settings.get("mail_from") or "",
        MAIL_PASSWORD=mail_password,
        MAIL_FROM=smtp_settings["mail_from"],
        MAIL_FROM_NAME=smtp_settings.get("mail_from_name") or get_settings().app_name,
        MAIL_PORT=int(smtp_settings["mail_port"]),
        MAIL_SERVER=smtp_settings["mail_server"],
        MAIL_STARTTLS=bool(smtp_settings["mail_starttls"]),
        MAIL_SSL_TLS=bool(smtp_settings["mail_ssl_tls"]),
        USE_CREDENTIALS=bool(smtp_settings["use_credentials"]),
        VALIDATE_CERTS=bool(smtp_settings["validate_certs"]),
        TEMPLATE_FOLDER=EMAIL_TEMPLATE_DIR,
    )


async def send_password_reset_email(
    connection: psycopg.Connection,
    *,
    recipient: str,
    username: str,
    reset_url: str,
) -> bool:
    config = build_mail_config(connection)
    if not config:
        return False
    message = MessageSchema(
        subject="OmniPBX Password Reset",
        recipients=[recipient],
        template_body={
            "username": username,
            "reset_url": reset_url,
            "app_name": get_settings().app_name,
            "expires_minutes": 30,
        },
        subtype=MessageType.html,
    )
    await FastMail(config).send_message(message, template_name="password_reset.html")
    return True


async def send_smtp_test_email(
    connection: psycopg.Connection,
    *,
    recipient: str,
) -> bool:
    config = build_mail_config(connection)
    if not config:
        return False
    message = MessageSchema(
        subject="OmniPBX SMTP Test",
        recipients=[recipient],
        template_body={
            "recipient": recipient,
            "app_name": get_settings().app_name,
        },
        subtype=MessageType.html,
    )
    await FastMail(config).send_message(message, template_name="smtp_test.html")
    return True
