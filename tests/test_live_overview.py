from unittest import TestCase
from unittest.mock import patch

import support  # noqa: F401

from app.features.live_overview.service import (
    _attach_call_quality,
    _build_active_users,
    _build_trunk_rows,
    _extensions_on_call,
    _ensure_chanspy_available,
    _hangup_existing_supervisor_spies,
    _parse_channel_quality_stats,
    _parse_active_calls,
    _parse_registration_status,
    _system_status,
    start_supervisor_action,
)
from app.features.live_overview.ui import _can_supervise_live_calls, _resolve_supervisor_extension


class LiveOverviewTests(TestCase):
    def test_supervisor_actions_require_supervise_permission_for_users(self):
        self.assertFalse(_can_supervise_live_calls({"role": "user"}, {"live_overview:view"}))
        self.assertTrue(_can_supervise_live_calls({"role": "user"}, {"live_overview:view", "live_overview:supervise"}))
        self.assertTrue(_can_supervise_live_calls({"role": "admin"}, set()))
        self.assertFalse(_can_supervise_live_calls({"role": "read_only"}, {"live_overview:supervise"}))

    def test_admin_can_select_enabled_supervisor_extension(self):
        with patch(
            "app.features.live_overview.ui.get_extension",
            return_value={"extension": "1001", "enabled": True},
        ):
            extension = _resolve_supervisor_extension(
                None,
                {"role": "admin", "extension": "10000"},
                selected_extension="1001",
            )

        self.assertEqual(extension, "1001")

    def test_agent_cannot_switch_supervisor_extension(self):
        with patch(
            "app.features.live_overview.ui.get_extension",
            return_value={"extension": "1002", "enabled": True},
        ) as get_extension:
            extension = _resolve_supervisor_extension(
                None,
                {"role": "agent", "extension": "1002"},
                selected_extension="1001",
            )

        self.assertEqual(extension, "1002")
        self.assertEqual(get_extension.call_args.args[1], "1002")

    def test_logged_in_extension_wins_over_selected_supervisor_extension(self):
        with patch(
            "app.features.live_overview.ui.get_extension",
            return_value={"extension": "1002", "enabled": True},
        ) as get_extension:
            extension = _resolve_supervisor_extension(
                None,
                {"role": "user", "extension": "1002"},
                selected_extension="10000",
            )

        self.assertEqual(extension, "1002")
        self.assertEqual(get_extension.call_args.args[1], "1002")

    def test_chanspy_readiness_loads_missing_module(self):
        with patch(
            "app.features.live_overview.service._run_asterisk_command",
            side_effect=[
                "Your application(s) is (are) not registered",
                "Loaded app_chanspy.so",
                "Info about Application 'ChanSpy'",
            ],
        ) as run_command:
            error = _ensure_chanspy_available()

        self.assertEqual(error, "")
        self.assertEqual(
            [call.args[0] for call in run_command.call_args_list],
            [
                "core show application ChanSpy",
                "module load app_chanspy.so",
                "core show application ChanSpy",
            ],
        )

    def test_hangup_existing_supervisor_spies_only_targets_same_supervisor_chanspy(self):
        output = "\n".join(
            [
                "PJSIP/10000-0000001d!omnipbx-internal!s!1!Up!ChanSpy!PJSIP/1002-0000001b,qbuE!10000",
                "PJSIP/10000-0000001e!omnipbx-internal!s!1!Up!ChanSpy!PJSIP/1002-0000001b,qbBuE!10000",
                "PJSIP/10000-0000001f!omnipbx-internal!1002!1!Up!Dial!PJSIP/1002!10000",
                "PJSIP/10001-00000020!omnipbx-internal!s!1!Up!ChanSpy!PJSIP/1002-0000001b,qbuE!10001",
            ]
        )

        with patch(
            "app.features.live_overview.service._run_asterisk_command",
            side_effect=[output, "", ""],
        ) as run_command:
            _hangup_existing_supervisor_spies("10000")

        self.assertEqual(
            [call.args[0] for call in run_command.call_args_list],
            [
                "core show channels concise",
                "channel request hangup PJSIP/10000-0000001d",
                "channel request hangup PJSIP/10000-0000001e",
            ],
        )

    def test_supervisor_action_rejects_monitor_extension_with_dnd(self):
        with (
            patch("app.features.live_overview.service._ensure_chanspy_available", return_value=""),
            patch("app.features.live_overview.service.collect_live_overview", return_value={"active_calls": [{"id": "PJSIP/1002-00000001"}]}),
            patch("app.features.live_overview.service.get_softphone_dnd", return_value=True),
        ):
            result = start_supervisor_action(None, supervisor_extension="10000", channel_id="PJSIP/1002-00000001", action="listen")

        self.assertFalse(result["ok"])
        self.assertIn("DND", result["message"])

    def test_supervisor_action_rejects_self_monitoring_same_channel_endpoint(self):
        with (
            patch("app.features.live_overview.service._ensure_chanspy_available", return_value=""),
            patch("app.features.live_overview.service.collect_live_overview", return_value={"active_calls": [{"id": "PJSIP/1002-00000001"}]}),
            patch("app.features.live_overview.service.get_softphone_dnd", return_value=False),
        ):
            result = start_supervisor_action(None, supervisor_extension="1002", channel_id="PJSIP/1002-00000001", action="listen")

        self.assertFalse(result["ok"])
        self.assertIn("different Monitor from", result["message"])

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

    def test_parse_active_calls_hides_unbridged_outbound_trunk_mirror(self):
        output = "\n".join(
            [
                "PJSIP/icc-00000011!from-trunk-icc!01911419050!1!Down!AppDial!(Outgoing Line)!01911419050!00:00:00!bridge!x!",
                "PJSIP/1001-00000010!from-internal-trunks!01911419050!1!Ringing!Dial!PJSIP/01911419050@icc!1001!00:00:00!bridge!x!",
            ]
        )

        calls = _parse_active_calls(output, [{"name": "icc"}])

        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["from"], "1001")
        self.assertEqual(calls[0]["to"], "01911419050")
        self.assertEqual(calls[0]["direction"], "Outgoing")
        self.assertEqual(calls[0]["trunk"], "icc")

    def test_parse_active_calls_hides_inbound_trunk_mirror_with_blank_destination(self):
        output = "\n".join(
            [
                "PJSIP/icc-00000021!from-trunk-icc!-!1!Up!AppDial!(Outgoing Line)!+8801303895377!00:00:00!bridge!x!",
                "PJSIP/icc-00000022!from-internal-trunks!+8801303895377!1!Up!Dial!PJSIP/+8801303895377@icc!09639145345!00:00:00!bridge!x!",
            ]
        )

        calls = _parse_active_calls(output, [{"name": "icc"}])

        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["from"], "09639145345")
        self.assertEqual(calls[0]["to"], "+8801303895377")
        self.assertEqual(calls[0]["direction"], "Outgoing")
        self.assertEqual(calls[0]["trunk"], "icc")

    def test_parse_active_calls_prefers_user_leg_for_bridged_outbound_call(self):
        output = "\n".join(
            [
                "PJSIP/icc-00000001!from-trunk-icc!!1!Up!AppDial!(Outgoing Line)!+8801911419050!00:00:49!!x!bridge-out",
                "PJSIP/1002-00000000!from-internal-trunks!+8801911419050!11!Up!Dial!PJSIP/icc/sip:01911419050@103.15.140.151:5060,60!09639145345!00:00:49!!x!bridge-out",
            ]
        )

        calls = _parse_active_calls(output, [{"name": "icc"}])

        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["id"], "PJSIP/1002-00000000")
        self.assertEqual(calls[0]["from"], "09639145345")
        self.assertEqual(calls[0]["to"], "+8801911419050")
        self.assertEqual(calls[0]["direction"], "Outgoing")
        self.assertEqual(calls[0]["trunk"], "icc")

    def test_attach_call_quality_uses_channelstats_uptime_when_duration_is_zero(self):
        calls = [
            {
                "id": "PJSIP/1002-00000000",
                "from": "09639145345",
                "to": "01911419050",
                "direction": "Outgoing",
                "duration": "00:00:00",
                "status": "Ringing",
                "status_class": "warn",
                "trunk": "icc",
            }
        ]
        stats = _parse_channel_quality_stats(
            "PJSIP/1002-00000000 00:00:17 ulaw 0 0 0 0 0 0 0 0 0"
        )

        updated = _attach_call_quality(calls, stats)

        self.assertEqual(updated[0]["duration"], "00:00:17")
        self.assertEqual(updated[0]["codec"], "ulaw")
        self.assertNotIn("uptime", updated[0])

    def test_parse_active_calls_collapses_inbound_route_to_answering_extension(self):
        output = "\n".join(
            [
                "PJSIP/icc-00000031!from-trunk-icc!s!1!Up!AppDial!(Outgoing Line)!01898828248!00:00:04!!x!bridge-123",
                "PJSIP/1001-00000032!omnipbx-internal!-!1!Up!AppDial!(Outgoing Line)!1001!00:00:03!!x!bridge-123",
            ]
        )

        calls = _parse_active_calls(output, [{"name": "icc"}])

        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["id"], "PJSIP/1001-00000032")
        self.assertEqual(calls[0]["from"], "01898828248")
        self.assertEqual(calls[0]["to"], "1001")
        self.assertEqual(calls[0]["direction"], "Incoming")
        self.assertEqual(calls[0]["trunk"], "icc")

    def test_parse_active_calls_hides_supervisor_spy_channel(self):
        output = "\n".join(
            [
                "PJSIP/10000-00000041!omnipbx-internal!s!1!Up!ChanSpy!PJSIP/1001-00000040,qbuE!10000!00:00:05!!x!",
                "PJSIP/1001-00000040!omnipbx-internal!1002!1!Up!Dial!PJSIP/1002!1001!00:00:10!!x!bridge-456",
                "PJSIP/1002-00000042!omnipbx-internal!-!1!Up!AppDial!(Outgoing Line)!1002!00:00:10!!x!bridge-456",
            ]
        )

        calls = _parse_active_calls(output, [{"name": "icc"}])

        self.assertEqual(len(calls), 1)
        self.assertNotEqual(calls[0]["id"], "PJSIP/10000-00000041")

    def test_parse_active_calls_hides_supervisor_originate_ringing_leg(self):
        output = "\n".join(
            [
                "PJSIP/1002-00000050!from-internal-trunks!+8801911419050!1!Up!Dial!PJSIP/icc/sip:01911419050@103.15.140.151:5060,60!09639145345!00:00:15!!x!bridge-live",
                "PJSIP/icc-00000051!from-trunk-icc!!1!Up!AppDial!(Outgoing Line)!+8801911419050!00:00:15!!x!bridge-live",
                "PJSIP/10000-00000052!omnipbx-internal!s!1!Ringing!AppDial!(Outgoing Line)!10000!00:00:03!!x!",
            ]
        )

        calls = _parse_active_calls(output, [{"name": "icc"}])

        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["id"], "PJSIP/1002-00000050")
        self.assertNotEqual(calls[0]["from"], "10000")

    def test_extensions_on_call_collects_numeric_participants(self):
        active = _extensions_on_call(
            [
                {"from": "1001", "to": "15551234567"},
                {"from": "anonymous", "to": "1002"},
                {"from": "", "to": "-"},
            ]
        )

        self.assertEqual(active, {"1001", "15551234567", "1002"})

    def test_channel_quality_stats_parser_grades_loss_jitter_and_codec(self):
        stats = _parse_channel_quality_stats(
            """
                                             ...........Receive......... .........Transmit..........
            BridgeId ChannelId ........ UpTime.. Codec.   Count    Lost Pct  Jitter   Count    Lost Pct  Jitter RTT....
            ===========================================================================================================
                     1001-00000047       00:00:02 opus       90       0    0   5.000     53       0    0   4.000  60.000
            bridge1  carrier-00000048    00:01:05 ulaw      900      30    3  35.000    860       1    0   8.000 190.000
            PJSIP/1002-00000049 not valid
            Objects found: 3
            """
        )

        self.assertEqual(stats["1001-00000047"]["codec"], "opus")
        self.assertEqual(stats["1001-00000047"]["quality"], "Good")
        self.assertEqual(stats["carrier-00000048"]["loss"], "3%")
        self.assertEqual(stats["carrier-00000048"]["quality"], "Fair")
        self.assertEqual(stats["carrier-00000048"]["quality_class"], "warn")
        self.assertEqual(stats["1002-00000049"]["quality"], "Collecting")

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
