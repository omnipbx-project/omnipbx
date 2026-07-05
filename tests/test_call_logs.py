from unittest import TestCase

import support  # noqa: F401

from app.services.call_logs import (
    _agent_call_log_condition,
    _is_supervisor_spy_cdr,
    agent_call_log_scope,
    visible_cdr_condition,
)


class CallLogsTests(TestCase):
    def test_supervisor_spy_cdr_rows_are_hidden(self):
        self.assertTrue(_is_supervisor_spy_cdr({"lastapp": "ChanSpy", "lastdata": "PJSIP/1001-0001,qbuE"}))
        self.assertTrue(_is_supervisor_spy_cdr({"lastapp": "AppDial", "lastdata": "ChanSpy(PJSIP/1001-0001,qbBuE)"}))
        self.assertFalse(_is_supervisor_spy_cdr({"lastapp": "Dial", "lastdata": "PJSIP/1001,60"}))

    def test_visible_cdr_condition_can_be_aliased(self):
        condition = visible_cdr_condition("c")

        self.assertIn("c.lastapp", condition)
        self.assertIn("c.lastdata", condition)

    def test_agent_call_log_condition_matches_call_participants(self):
        condition = _agent_call_log_condition()

        self.assertIn("caller_extension", condition)
        self.assertIn("callee_extension", condition)
        self.assertIn("src", condition)
        self.assertIn("dst", condition)
        self.assertIn("%(agent_extension)s", condition)

    def test_agent_extension_scope_only_applies_to_extension_users(self):
        self.assertEqual(agent_call_log_scope({"role": "user", "extension": "1001", "username": "1001"}), "1001")
        self.assertIsNone(agent_call_log_scope({"role": "admin", "username": "admin"}))

    def test_call_log_view_permission_allows_extension_to_see_all_logs(self):
        self.assertIsNone(
            agent_call_log_scope(
                {"role": "user", "extension": "1002", "username": "1002"},
                {"call_logs:view"},
            )
        )
