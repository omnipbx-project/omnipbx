from datetime import UTC
from unittest import TestCase

from app.services.date_ranges import parse_date_bound, resolve_date_range


class DateRangeTests(TestCase):
    def test_parse_date_bound_uses_configured_timezone(self):
        start = parse_date_bound("2026-06-08", end_of_day=False, timezone_name="Asia/Dhaka")
        end = parse_date_bound("2026-06-08", end_of_day=True, timezone_name="Asia/Dhaka")

        self.assertIsNotNone(start)
        self.assertIsNotNone(end)
        self.assertEqual(start.tzinfo, UTC)
        self.assertEqual(end.tzinfo, UTC)
        self.assertEqual(start.isoformat(), "2026-06-07T18:00:00+00:00")
        self.assertEqual(end.isoformat(), "2026-06-08T17:59:59+00:00")

    def test_custom_range_keeps_clean_dates(self):
        resolved = resolve_date_range(
            "custom",
            date_from="2026-01-15",
            date_to="2026-01-20",
            timezone_name="Asia/Dhaka",
        )

        self.assertEqual(resolved.key, "custom")
        self.assertTrue(resolved.is_custom)
        self.assertEqual(resolved.date_from, "2026-01-15")
        self.assertEqual(resolved.date_to, "2026-01-20")

    def test_all_range_has_no_bounds(self):
        resolved = resolve_date_range("all", timezone_name="Asia/Dhaka")

        self.assertEqual(resolved.key, "all")
        self.assertEqual(resolved.date_from, "")
        self.assertEqual(resolved.date_to, "")
