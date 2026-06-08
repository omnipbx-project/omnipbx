from unittest import TestCase

import support  # noqa: F401

from app.features.live_overview.service import (
    _build_active_users,
    _build_trunk_rows,
    _extensions_on_call,
    _parse_active_calls,
    _parse_registration_status,
    _system_status,
)


class LiveOverviewTests(TestCase):
    def test_parse_active_calls_deduplicates_bridged_channels_and_infers_direction(self):
        output = "\n".join(
            [
                "PJSIP/1001-00000001!from-internal-trunks!15551234567!1!Up!AppDial!(Outgoing Line)!1001!00:02:10!bridge!x!PJSIP/carrier-00000002",
                "PJSIP/carrier-00000002!from-trunk-carrier!15551234567!1!Up!AppDial!(Outgoing Line)!15551234567!00:02:10!bridge!x!PJSIP/1001-00000001",
                "PJSIP/1002-00000003!omnipbx-internal!1002!1!Ring!AppDial!(Outgoing Line)!1002!00:00:04!bridge!x!",
                "PJSIP/carrier-00000004!from-trunk-carrier!s!1!Ringing!AppDial!PJSIP/1003!15557654321!00:00:08!bridge!x!",
                "not a concise channel line",
            ]
        )

        calls = _parse_active_calls(output, [{"name": "carrier"}])

        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0]["id"], "PJSIP/1001-00000001")
        self.assertEqual(calls[0]["direction"], "Outgoing")
        self.assertEqual(calls[0]["status"], "Connected")
        self.assertEqual(calls[0]["trunk"], "carrier")
        self.assertEqual(calls[1]["direction"], "Incoming")
        self.assertEqual(calls[1]["status"], "Ringing")

    def test_extensions_on_call_collects_numeric_participants(self):
        active = _extensions_on_call(
            [
                {"from": "1001", "to": "15551234567"},
                {"from": "anonymous", "to": "1002"},
                {"from": "", "to": "-"},
            ]
        )

        self.assertEqual(active, {"1001", "15551234567", "1002"})

    def test_registration_status_parser_handles_common_asterisk_states(self):
        statuses = _parse_registration_status(
            """
            <Registration/ServerURI..............................> <Auth..........> <Status.......>
            reg-carrier/sip:sip.example.com                         auth-carrier     Registered
            reg-backup/sip:backup.example.com                        auth-backup      Rejected
            reg-spare/sip:spare.example.com                          auth-spare       Unregistered
            Objects found: 3
            """
        )

        self.assertEqual(statuses["carrier"], "Registered")
        self.assertEqual(statuses["backup"], "Rejected")
        self.assertEqual(statuses["spare"], "Unregistered")

    def test_trunk_rows_translate_registration_state_and_active_counts(self):
        rows = _build_trunk_rows(
            [
                {"name": "carrier", "provider_name": "Carrier", "host": "sip.example.com", "enabled": True, "register_enabled": True},
                {"name": "ippeer", "provider_name": "", "host": "198.51.100.20", "enabled": True, "register_enabled": False},
                {"name": "disabled", "provider_name": "", "host": "sip.disabled", "enabled": False, "register_enabled": True},
            ],
            {"carrier": "Registered", "disabled": "Rejected"},
            [{"trunk": "carrier"}, {"trunk": "carrier"}, {"trunk": "ippeer"}],
        )

        self.assertEqual(rows[0]["status"], "Online")
        self.assertEqual(rows[0]["active_calls"], 2)
        self.assertEqual(rows[1]["status"], "Warning")
        self.assertEqual(rows[1]["message"], "IP based connection")
        self.assertEqual(rows[2]["status"], "Offline")
        self.assertEqual(rows[2]["message"], "Disabled")

    def test_active_users_are_sorted_by_operational_priority(self):
        users = _build_active_users(
            [
                {"extension": "1003", "display_name": "Carol", "status": "Offline"},
                {"extension": "1001", "display_name": "Alice", "status": "Online"},
                {"extension": "1002", "display_name": "Bob", "status": "Online"},
            ],
            {"1001": {"group_name": "Support"}},
            {"1002"},
        )

        self.assertEqual([user["extension"] for user in users], ["1002", "1001", "1003"])
        self.assertEqual(users[0]["status"], "On Call")
        self.assertEqual(users[1]["group"], "Support")

    def test_system_status_prefers_errors_then_offline_trunks_then_healthy(self):
        self.assertEqual(_system_status(["AMI down"], [])["label"], "Needs Attention")
        self.assertEqual(_system_status([], [{"status": "Offline"}])["message"], "One or more trunks need attention.")
        self.assertEqual(_system_status([], [{"status": "Online"}])["label"], "Healthy")
