from datetime import UTC, datetime, timedelta
from unittest import TestCase
from unittest.mock import patch

import support  # noqa: F401

from app.services.auth import (
    get_reset_token_record,
    hash_password,
    is_reset_token_usable,
    issue_session_cookie,
    resolve_session,
    verify_password,
)


class AuthTests(TestCase):
    def test_password_hash_verifies_only_original_password(self):
        password_hash = hash_password("correct horse battery staple")

        self.assertTrue(verify_password("correct horse battery staple", password_hash))
        self.assertFalse(verify_password("wrong password", password_hash))
        self.assertFalse(verify_password("anything", "not-a-valid-hash"))
        self.assertFalse(verify_password("anything", "bcrypt$salt$digest"))

    def test_admin_session_cookie_round_trips_and_rejects_tampering(self):
        password_hash = "scrypt$marker$hash"
        admin = {
            "id": 7,
            "username": "owner",
            "password_hash": password_hash,
            "role": "owner",
            "is_owner": True,
            "principal_type": "admin",
        }

        with patch("app.services.auth._get_or_create_secret", return_value="session-secret"):
            cookie = issue_session_cookie(object(), admin)
            with patch("app.services.auth.get_admin_by_id", return_value=admin.copy()) as get_admin:
                resolved = resolve_session(object(), cookie)

            tampered = cookie[:-1] + ("A" if cookie[-1] != "A" else "B")
            rejected = resolve_session(object(), tampered)

        self.assertEqual(resolved["username"], "owner")
        get_admin.assert_called_once()
        self.assertIsNone(rejected)

    def test_extension_session_cookie_uses_extension_identity(self):
        extension_user = {
            "id": 12,
            "username": "1001",
            "extension": "1001",
            "display_name": "Support",
            "password_hash": "phone-secret",
            "role": "user",
            "is_owner": False,
            "principal_type": "extension",
        }

        with patch("app.services.auth._get_or_create_secret", return_value="session-secret"):
            cookie = issue_session_cookie(object(), extension_user)
            with patch("app.services.auth.get_extension_user_by_id", return_value=extension_user.copy()):
                resolved = resolve_session(object(), cookie)

        self.assertEqual(resolved["principal_type"], "extension")
        self.assertEqual(resolved["extension"], "1001")

    def test_reset_token_usability_requires_present_unused_unexpired_record(self):
        future = datetime.now(UTC) + timedelta(minutes=5)
        past = datetime.now(UTC) - timedelta(minutes=5)

        self.assertTrue(is_reset_token_usable({"expires_at": future, "used_at": None}))
        self.assertFalse(is_reset_token_usable(None))
        self.assertFalse(is_reset_token_usable({"expires_at": future, "used_at": datetime.now(UTC)}))
        self.assertFalse(is_reset_token_usable({"expires_at": past, "used_at": None}))
        self.assertFalse(is_reset_token_usable({"used_at": None}))

    def test_get_reset_token_record_hashes_raw_token_before_query(self):
        class Cursor:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def execute(self, query, params):
                self.params = params

            def fetchone(self):
                return {"id": 1, "admin_user_id": 2, "username": "owner", "email": "owner@example.com"}

        class Connection:
            def __init__(self):
                self.cursor_instance = Cursor()

            def cursor(self, row_factory=None):
                return self.cursor_instance

        connection = Connection()
        record = get_reset_token_record(connection, "raw-token-value")

        self.assertEqual(record["username"], "owner")
        self.assertNotEqual(connection.cursor_instance.params["token_hash"], "raw-token-value")
        self.assertEqual(len(connection.cursor_instance.params["token_hash"]), 64)
