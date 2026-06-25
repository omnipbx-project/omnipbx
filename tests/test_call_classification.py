from unittest import TestCase

import support  # noqa: F401

from app.services.call_classification import (
    abandoned_call_condition,
    call_type_label,
    customer_missed_call_condition,
    is_abandoned_call,
    is_callback_candidate,
    is_customer_missed_call,
)


class CallClassificationTests(TestCase):
    def test_inbound_missed_extension_is_customer_missed(self):
        row = {
            "direction": "inbound",
            "disposition": "NO ANSWER",
            "callee_extension": "1001",
            "queue_name": "",
            "ivr_name": "",
        }

        self.assertTrue(is_customer_missed_call(row))
        self.assertTrue(is_callback_candidate(row))
        self.assertEqual(call_type_label(row), "Missed")

    def test_queue_no_answer_is_abandoned_not_customer_missed(self):
        row = {
            "direction": "inbound",
            "disposition": "NO ANSWER",
            "callee_extension": "1001",
            "queue_name": "Support",
            "ivr_name": "",
        }

        self.assertTrue(is_abandoned_call(row))
        self.assertFalse(is_customer_missed_call(row))
        self.assertTrue(is_callback_candidate(row))
        self.assertEqual(call_type_label(row), "Abandoned")

    def test_outbound_and_internal_failures_are_not_customer_missed(self):
        for direction in ("outbound", "internal"):
            row = {
                "direction": direction,
                "disposition": "NO ANSWER",
                "callee_extension": "1001",
                "queue_name": "",
                "ivr_name": "",
            }

            self.assertFalse(is_customer_missed_call(row))
            self.assertFalse(is_abandoned_call(row))
            self.assertFalse(is_callback_candidate(row))

    def test_sql_conditions_support_optional_aliases(self):
        missed_sql = customer_missed_call_condition("c")
        abandoned_sql = abandoned_call_condition("c")

        self.assertIn("c.direction", missed_sql)
        self.assertIn("c.disposition = ANY(%(missed)s)", missed_sql)
        self.assertIn("c.queue_name", abandoned_sql)
        self.assertIn("c.ivr_name", abandoned_sql)
