from unittest import TestCase

import support  # noqa: F401

from app.services.auto_dialer import _normalize_phone_pair, detect_phone_column, parse_lead_file, parse_pasted_leads


class AutoDialerLeadImportTests(TestCase):
    def test_parse_csv_contacts_and_detect_phone_column(self):
        rows, columns = parse_lead_file(
            "leads.csv",
            b"Name,Mobile,Company\nCustomer One,01711111111,Acme\n",
        )

        self.assertEqual(rows[0]["Name"], "Customer One")
        self.assertEqual(rows[0]["Mobile"], "01711111111")
        self.assertEqual(detect_phone_column(columns), "Mobile")

    def test_parse_plain_text_numbers(self):
        rows, columns = parse_pasted_leads("Customer One, 01711111111\n01722222222")

        self.assertEqual(rows[0]["lead_name"], "Customer One")
        self.assertEqual(rows[0]["phone_number"], "01711111111")
        self.assertEqual(rows[1]["phone_number"], "01722222222")
        self.assertIn("phone_number", columns)

    def test_normalize_phone_pair_builds_asterisk_safe_dial_number(self):
        display_number, dial_number = _normalize_phone_pair("01711-111111", "+880")

        self.assertEqual(display_number, "01711111111")
        self.assertEqual(dial_number, "01711111111")

    def test_parse_headerless_csv_number_as_lead(self):
        rows, columns = parse_lead_file("leads.csv", b"01711-111111\n")

        self.assertEqual(rows[0]["phone_number"], "01711-111111")
        self.assertIn("phone_number", columns)

    def test_detect_phone_column_from_values_when_headers_are_generic(self):
        rows = [
            {"Name": "Customer One", "Column A": "Acme", "Column B": "01711-111111"},
            {"Name": "Customer Two", "Column A": "Beta", "Column B": "01722222222"},
        ]

        self.assertEqual(detect_phone_column(["Name", "Column A", "Column B"], rows), "Column B")

    def test_detect_phone_column_does_not_guess_first_unrelated_column(self):
        self.assertEqual(detect_phone_column(["Name", "Company"]), "")
