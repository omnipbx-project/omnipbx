from unittest import TestCase

import support  # noqa: F401

from app.services.security import _clean_ip, _ip_matches_any


class SecurityTests(TestCase):
    def test_clean_ip_strips_ports_and_rejects_invalid_values(self):
        self.assertEqual(_clean_ip("203.0.113.10:5060"), "203.0.113.10")
        self.assertEqual(_clean_ip("[2001:db8::1]:443"), "2001:db8::1")
        self.assertEqual(_clean_ip("not an ip"), "")

    def test_ip_matches_exact_addresses_and_cidrs(self):
        self.assertTrue(_ip_matches_any("203.0.113.10", ["203.0.113.10"]))
        self.assertTrue(_ip_matches_any("203.0.113.10", ["203.0.113.0/24"]))
        self.assertTrue(_ip_matches_any("2001:db8::1", ["2001:db8::/32"]))
        self.assertFalse(_ip_matches_any("203.0.114.10", ["203.0.113.0/24"]))
        self.assertFalse(_ip_matches_any("not an ip", ["203.0.113.0/24"]))
        self.assertFalse(_ip_matches_any("203.0.113.10", ["not a rule"]))
