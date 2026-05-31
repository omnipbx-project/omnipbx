from __future__ import annotations

import argparse
import ipaddress
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import psycopg
from psycopg.rows import dict_row
from starlette.requests import Request


LOGIN_WINDOW_MINUTES = 15
LOGIN_FAILURE_LIMIT = 5
BAN_MINUTES = 30


@dataclass(frozen=True)
class SecurityDecision:
    allowed: bool
    reason: str = ""
    rule: str = ""


def client_ip_from_request(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "").split(",", 1)[0].strip()
    real_ip = request.headers.get("x-real-ip", "").strip()
    raw = forwarded or real_ip or (request.client.host if request.client else "")
    return _clean_ip(raw)


def request_security_decision(connection: psycopg.Connection, request: Request) -> SecurityDecision:
    ip = client_ip_from_request(request)
    if not ip:
        return SecurityDecision(True)
    if _matches_rule(connection, "ip_whitelist", ip):
        return SecurityDecision(True, rule="ip_whitelist")
    if _matches_rule(connection, "ip_blocklist", ip):
        return SecurityDecision(False, "This IP is blocked in OmniPBX security settings.", "ip_blocklist")
    if _active_ban(connection, "ip", ip):
        return SecurityDecision(False, "Too many failed attempts. This IP is temporarily blocked.", "built_in_ban")
    return SecurityDecision(True)


def username_security_decision(connection: psycopg.Connection, username: str) -> SecurityDecision:
    value = username.strip().lower()
    if not value:
        return SecurityDecision(True)
    if _matches_rule(connection, "admin_user_block", value, exact=True):
        return SecurityDecision(False, "This admin username is blocked in OmniPBX security settings.", "admin_user_block")
    if _active_ban(connection, "user", value):
        return SecurityDecision(False, "Too many failed attempts for this username. It is temporarily blocked.", "built_in_ban")
    return SecurityDecision(True)


def record_login_failure(connection: psycopg.Connection, *, request: Request, username: str) -> dict[str, object]:
    ip = client_ip_from_request(request)
    user = username.strip().lower() or "unknown"
    now = datetime.now(timezone.utc)
    window_start = now - timedelta(minutes=LOGIN_WINDOW_MINUTES)
    ban_until = now + timedelta(minutes=BAN_MINUTES)
    result = {"ip": ip, "username": user, "banned": False}

    with connection.cursor(row_factory=dict_row) as cursor:
        for subject_type, value in (("ip", ip), ("user", user)):
            if not value:
                continue
            cursor.execute(
                """
                INSERT INTO app_security_failures (subject_type, subject_value, failed_attempts, first_seen, last_seen)
                VALUES (%(type)s, %(value)s, 1, NOW(), NOW())
                ON CONFLICT (subject_type, subject_value) DO UPDATE
                SET failed_attempts = CASE
                        WHEN app_security_failures.first_seen < %(window_start)s THEN 1
                        ELSE app_security_failures.failed_attempts + 1
                    END,
                    first_seen = CASE
                        WHEN app_security_failures.first_seen < %(window_start)s THEN NOW()
                        ELSE app_security_failures.first_seen
                    END,
                    last_seen = NOW()
                RETURNING failed_attempts
                """,
                {"type": subject_type, "value": value, "window_start": window_start},
            )
            failures = int(cursor.fetchone()["failed_attempts"])
            if failures >= LOGIN_FAILURE_LIMIT:
                cursor.execute(
                    """
                    INSERT INTO app_security_bans (subject_type, subject_value, reason, failed_attempts, banned_until, enabled)
                    VALUES (%(type)s, %(value)s, %(reason)s, %(failed_attempts)s, %(banned_until)s, TRUE)
                    ON CONFLICT (subject_type, subject_value) DO UPDATE
                    SET reason = EXCLUDED.reason,
                        failed_attempts = EXCLUDED.failed_attempts,
                        banned_until = EXCLUDED.banned_until,
                        enabled = TRUE,
                        updated_at = NOW()
                    """,
                    {
                        "type": subject_type,
                        "value": value,
                        "reason": "Too many failed admin login attempts",
                        "failed_attempts": failures,
                        "banned_until": ban_until,
                    },
                )
                result["banned"] = True
    return result


def record_login_success(connection: psycopg.Connection, *, request: Request, username: str) -> None:
    ip = client_ip_from_request(request)
    user = username.strip().lower()
    with connection.cursor() as cursor:
        cursor.execute(
            """
            DELETE FROM app_security_failures
            WHERE (subject_type = 'ip' AND subject_value = %(ip)s)
               OR (subject_type = 'user' AND subject_value = %(user)s)
            """,
            {"ip": ip, "user": user},
        )


def list_app_bans(connection: psycopg.Connection) -> list[dict]:
    with connection.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT id, subject_type, subject_value, reason, failed_attempts, enabled,
                   TO_CHAR(banned_until, 'YYYY-MM-DD HH24:MI:SS') AS banned_until,
                   banned_until > NOW() AS active,
                   TO_CHAR(updated_at, 'YYYY-MM-DD HH24:MI:SS') AS updated_at
            FROM app_security_bans
            ORDER BY active DESC, updated_at DESC
            LIMIT 100
            """
        )
        return [dict(row) for row in cursor.fetchall()]


def unblock_app_ban(connection: psycopg.Connection, ban_id: int) -> bool:
    with connection.cursor(row_factory=dict_row) as cursor:
        cursor.execute("UPDATE app_security_bans SET enabled = FALSE, updated_at = NOW() WHERE id = %(id)s RETURNING id", {"id": ban_id})
        return bool(cursor.fetchone())


def unblock_subject(connection: psycopg.Connection, *, subject_type: str, subject_value: str) -> int:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            UPDATE app_security_bans
            SET enabled = FALSE, updated_at = NOW()
            WHERE subject_type = %(type)s AND subject_value = %(value)s AND enabled = TRUE
            """,
            {"type": subject_type, "value": subject_value},
        )
        bans = cursor.rowcount
        cursor.execute(
            "DELETE FROM app_security_failures WHERE subject_type = %(type)s AND subject_value = %(value)s",
            {"type": subject_type, "value": subject_value},
        )
        rule_type = {"ip": "ip_blocklist", "user": "admin_user_block"}.get(subject_type)
        if rule_type:
            cursor.execute(
                """
                UPDATE advanced_security_rules
                SET enabled = FALSE, updated_at = NOW()
                WHERE rule_type = %(rule_type)s AND lower(value) = lower(%(value)s) AND enabled = TRUE
                """,
                {"rule_type": rule_type, "value": subject_value},
            )
            bans += cursor.rowcount
    return bans


def app_security_status(connection: psycopg.Connection) -> dict[str, object]:
    with connection.cursor(row_factory=dict_row) as cursor:
        cursor.execute("SELECT COUNT(*) AS total FROM advanced_security_rules WHERE enabled = TRUE AND rule_type = 'ip_blocklist'")
        blocked_ips = int(cursor.fetchone()["total"])
        cursor.execute("SELECT COUNT(*) AS total FROM advanced_security_rules WHERE enabled = TRUE AND rule_type = 'ip_whitelist'")
        trusted_ips = int(cursor.fetchone()["total"])
        cursor.execute("SELECT COUNT(*) AS total FROM app_security_bans WHERE enabled = TRUE AND banned_until > NOW()")
        active_bans = int(cursor.fetchone()["total"])
    return {
        "ok": True,
        "mode": "Built-in OmniPBX protection",
        "output": "OmniPBX is protecting the web app with internal IP allow/block rules and automatic login bans.",
        "trusted_ips": trusted_ips,
        "blocked_ips": blocked_ips,
        "active_bans": active_bans,
        "login_failure_limit": LOGIN_FAILURE_LIMIT,
        "login_window_minutes": LOGIN_WINDOW_MINUTES,
        "ban_minutes": BAN_MINUTES,
    }


def run_cli(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.cli", description="OmniPBX maintenance CLI")
    subparsers = parser.add_subparsers(dest="command")
    unblock = subparsers.add_parser("security-unblock", help="Unblock an IP or admin username")
    unblock.add_argument("--ip", default="", help="IP address to unblock")
    unblock.add_argument("--user", default="", help="Admin username to unblock")
    args = parser.parse_args(argv)

    if args.command == "security-unblock":
        from app.core.settings import get_settings

        settings = get_settings()
        with psycopg.connect(settings.db_dsn, autocommit=True) as connection:
            if args.ip:
                value = _clean_ip(args.ip)
                count = unblock_subject(connection, subject_type="ip", subject_value=value)
                print(f"Unblocked IP {value}. Updated bans: {count}")
                return 0
            if args.user:
                value = args.user.strip().lower()
                count = unblock_subject(connection, subject_type="user", subject_value=value)
                print(f"Unblocked user {value}. Updated bans: {count}")
                return 0
        print("Use --ip 1.2.3.4 or --user admin")
        return 2

    parser.print_help()
    return 2


def _active_ban(connection: psycopg.Connection, subject_type: str, subject_value: str) -> bool:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT 1 FROM app_security_bans
            WHERE subject_type = %(type)s
              AND subject_value = %(value)s
              AND enabled = TRUE
              AND banned_until > NOW()
            LIMIT 1
            """,
            {"type": subject_type, "value": subject_value},
        )
        return bool(cursor.fetchone())


def _matches_rule(connection: psycopg.Connection, rule_type: str, value: str, *, exact: bool = False) -> bool:
    with connection.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            "SELECT value FROM advanced_security_rules WHERE rule_type = %(type)s AND enabled = TRUE",
            {"type": rule_type},
        )
        rules = [str(row["value"]).strip() for row in cursor.fetchall()]
    if exact:
        return value.lower() in {rule.lower() for rule in rules}
    return _ip_matches_any(value, rules)


def _ip_matches_any(value: str, rules: list[str]) -> bool:
    try:
        ip = ipaddress.ip_address(value)
    except ValueError:
        return False
    for rule in rules:
        try:
            if ip in ipaddress.ip_network(rule, strict=False):
                return True
        except ValueError:
            if value == rule:
                return True
    return False


def _clean_ip(value: str) -> str:
    value = (value or "").strip()
    if value.startswith("[") and "]" in value:
        return value[1:value.index("]")]
    if value.count(":") == 1 and "." in value:
        return value.rsplit(":", 1)[0]
    return value


if __name__ == "__main__":
    raise SystemExit(run_cli(sys.argv[1:]))
