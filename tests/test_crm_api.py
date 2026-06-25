from unittest import TestCase

import support  # noqa: F401

from app.services.crm_api import is_valid_crm_api_key


class _Cursor:
    def __init__(self, api_key):
        self.api_key = api_key

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def execute(self, *_args, **_kwargs):
        return None

    def fetchone(self):
        return {"api_key": self.api_key}


class _Connection:
    def __init__(self, api_key):
        self.api_key = api_key

    def cursor(self, *args, **kwargs):
        return _Cursor(self.api_key)


class CrmApiAuthTests(TestCase):
    def test_validates_configured_api_key(self):
        connection = _Connection("shared-secret")

        self.assertTrue(is_valid_crm_api_key(connection, "shared-secret"))
        self.assertFalse(is_valid_crm_api_key(connection, "wrong-secret"))
        self.assertFalse(is_valid_crm_api_key(connection, None))

    def test_blank_configured_api_key_disables_crm_api_access(self):
        self.assertFalse(is_valid_crm_api_key(_Connection(""), "anything"))
        self.assertFalse(is_valid_crm_api_key(_Connection(None), "anything"))
