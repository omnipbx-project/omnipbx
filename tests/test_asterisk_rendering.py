from unittest import TestCase
from unittest.mock import patch

import support  # noqa: F401

from app.services.asterisk import (
    _attach_group_members,
    _attach_ivr_options,
    render_extensions_config,
    render_inbound_routes_config,
    render_pjsip_base_config,
    render_pjsip_config,
    render_ring_groups_config,
    render_trunk_dialplan,
    render_trunk_pjsip_config,
    render_voicemail_config,
)


class AsteriskRenderingTests(TestCase):
    def test_pjsip_base_uses_first_safe_public_host(self):
        config = render_pjsip_base_config(
            {
                "sip_domain": "bad host!",
                "public_host": "",
                "public_base_url": "https://pbx.example.com:8443/app",
            }
        )

        self.assertIn("external_signaling_address = pbx.example.com", config)
        self.assertIn("external_media_address = pbx.example.com", config)
        self.assertNotIn("bad host", config)

    def test_pjsip_extension_rendering_separates_webphone_and_desk_phone_options(self):
        config = render_pjsip_config(
            [
                {
                    "extension": "1001",
                    "display_name": "Desk",
                    "secret": "desk-secret",
                    "context": "omnipbx-internal",
                    "transport": "transport-udp",
                    "codecs": "ulaw,alaw",
                    "video_codecs": "",
                    "simultaneous_device_limit": 2,
                },
                {
                    "extension": "1002",
                    "display_name": "Web",
                    "secret": "web-secret",
                    "context": "omnipbx-internal",
                    "transport": "transport-wss",
                    "codecs": "ulaw,alaw",
                    "video_codecs": "h264",
                    "simultaneous_device_limit": 20,
                },
            ]
        )

        self.assertIn("[1001]\ntype = endpoint\ntransport = transport-udp", config)
        self.assertIn("allow = ulaw,alaw", config)
        self.assertIn("[1002]\ntype = endpoint\ntransport = transport-wss", config)
        self.assertIn("webrtc = yes", config)
        self.assertIn("max_contacts = 10", config)
        self.assertIn("qualify_frequency = 0", config)

    def test_trunk_pjsip_config_renders_registration_identify_and_ip_contact_modes(self):
        config = render_trunk_pjsip_config(
            [
                {
                    "name": "carrier",
                    "host": "sip.carrier.test",
                    "username": "acct",
                    "password": "secret",
                    "transport": "transport-udp",
                    "codecs": "ulaw",
                    "register_enabled": True,
                    "match_ip": "203.0.113.10",
                },
                {
                    "name": "ippeer",
                    "host": "198.51.100.20",
                    "username": None,
                    "password": None,
                    "transport": "transport-tcp",
                    "codecs": "ulaw,alaw",
                    "register_enabled": False,
                    "match_ip": None,
                },
            ]
        )

        self.assertIn("[reg-carrier]", config)
        self.assertIn("server_uri = sip:sip.carrier.test", config)
        self.assertIn("client_uri = sip:acct@sip.carrier.test", config)
        self.assertIn("[identify-carrier]", config)
        self.assertIn("match = 203.0.113.10", config)
        self.assertIn("contact = sip:198.51.100.20", config)
        self.assertIn("[identify-ippeer]", config)
        self.assertNotIn("[reg-ippeer]", config)

    def test_inbound_routes_include_working_hours_welcome_and_advanced_blocklist(self):
        with patch("app.services.asterisk.normalize_sound_name", side_effect=lambda value: value):
            config = render_inbound_routes_config(
                [
                    {
                        "name": "main",
                        "trunk_name": "carrier",
                        "did_pattern": "",
                        "destination_type": "queue",
                        "destination_value": "600",
                    }
                ],
                queues=[{"extension": "600", "name": "support", "max_wait_time": 45}],
                ivrs=[],
                ring_groups=[],
                working_hours=[
                    {
                        "name": "office",
                        "start_day": "monday",
                        "end_day": "friday",
                        "start_time": "09:00",
                        "end_time": "17:00",
                        "inbound_route_name": "main",
                        "after_hours_sound": "closed",
                    }
                ],
                welcome_messages=[{"inbound_route_name": "main", "sound_name": "welcome"}],
                advanced_security_rules=[
                    {"rule_type": "number_block", "value": "+15551230000", "enabled": True}
                ],
            )

        self.assertIn("[from-trunk-carrier]", config)
        self.assertIn("Goto(inbound-route-main,s,1)", config)
        self.assertIn("GotoIfTime(09:00-17:00,mon-fri,*,*?open-hours,1)", config)
        self.assertIn("Playback(welcome)", config)
        self.assertIn("Queue(support,t,,,45)", config)
        self.assertIn("Playback(closed)", config)
        self.assertIn("+15551230000", config)

    def test_internal_dialplan_honors_group_calling_rules_and_voicemail(self):
        config = render_extensions_config(
            [
                {
                    "extension": "1001",
                    "display_name": "Alice",
                    "call_recording_enabled": True,
                },
                {
                    "extension": "1002",
                    "display_name": "Bob",
                    "call_recording_enabled": False,
                },
            ],
            call_routing_rules=[
                {
                    "section_slug": "internal-calls",
                    "item_slug": "calling-rules",
                    "name": "support-only",
                    "config_json": {
                        "source_type": "group",
                        "source_values": "Support",
                        "destination_type": "group",
                        "destination_values": "Support",
                    },
                },
                {
                    "section_slug": "internal-calls",
                    "item_slug": "voicemail",
                    "name": "bob-vm",
                    "config_json": {
                        "extension": "1002",
                        "mailbox": "1002",
                        "when": "no_answer",
                        "timeout": "25",
                    },
                },
            ],
            user_profiles=[
                {"extension": "1001", "group_name": "Support"},
                {"extension": "1002", "group_name": "Support"},
            ],
        )

        self.assertIn('GotoIf($["${CALLERID(num)}" = "1001" | "${CALLERID(num)}" = "1002"]?allowed)', config)
        self.assertIn("Dial(PJSIP/1002,25)", config)
        self.assertIn('GotoIf($["${DIALSTATUS}" = "NOANSWER"]?send-vm)', config)
        self.assertIn("VoiceMail(1002@default,u)", config)
        self.assertIn("MixMonitor(${OMNI_RECORDING_FILE},b)", config)

    def test_ring_group_linear_strategy_and_empty_fallback_are_rendered(self):
        empty_config = render_ring_groups_config([])
        linear_config = render_ring_groups_config(
            [
                {
                    "name": "support",
                    "extension": "700",
                    "ring_strategy": "linear",
                    "ring_timeout": 15,
                    "members": ["1001", "1002"],
                }
            ]
        )

        self.assertIn("exten => _X.,1,Hangup()", empty_config)
        self.assertIn("same => n(start),Dial(PJSIP/1001,15)", linear_config)
        self.assertIn("same => n(try2),Dial(PJSIP/1002,15)", linear_config)

    def test_trunk_dialplan_renders_route_rules_before_legacy_prefix_routes(self):
        config = render_trunk_dialplan(
            [
                {
                    "name": "carrier",
                    "host": "sip.carrier.test",
                    "outbound_prefix": "9",
                    "strip_digits": 0,
                    "register_enabled": True,
                }
            ],
            call_routing_rules=[
                {
                    "section_slug": "outgoing-calls",
                    "item_slug": "routes",
                    "name": "national",
                    "config_json": {
                        "dial_pattern": "0X.",
                        "trunk": "carrier",
                        "strip_digits": "1",
                        "add_prefix": "88",
                        "source_type": "any",
                    },
                }
            ],
        )

        self.assertIn("exten => _0X.,1,NoOp(Outgoing route national)", config)
        self.assertIn("Set(OUTNUM=88${EXTEN:1})", config)
        self.assertIn("Dial(PJSIP/${OUTNUM}@carrier,60)", config)
        self.assertIn("exten => _9X.,1,NoOp(Outbound via trunk carrier)", config)

    def test_voicemail_config_combines_extension_and_inbound_rule_mailboxes(self):
        config = render_voicemail_config(
            [{"extension": "1001", "display_name": "Alice"}],
            [
                {
                    "section_slug": "incoming-calls",
                    "item_slug": "voicemail",
                    "config_json": {"mailbox": "9000"},
                }
            ],
        )

        self.assertIn("1001 => 1001,Alice", config)
        self.assertIn("9000 => 9000,9000", config)

    def test_attach_helpers_preserve_parent_rows_without_members_or_options(self):
        groups = _attach_group_members(
            [{"id": 1, "name": "support"}, {"id": 2, "name": "sales"}],
            [{"ring_group_id": 1, "extension": "1001"}],
            "id",
            "ring_group_id",
        )
        ivrs = _attach_ivr_options(
            [{"id": 10, "name": "main"}, {"id": 11, "name": "after-hours"}],
            [{"ivr_id": 10, "digit": "1", "destination_type": "queue", "destination_value": "600"}],
        )

        self.assertEqual(groups[0]["members"], ["1001"])
        self.assertEqual(groups[1]["members"], [])
        self.assertEqual(ivrs[0]["options"][0]["digit"], "1")
        self.assertEqual(ivrs[1]["options"], [])
