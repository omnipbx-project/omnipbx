from unittest import TestCase

import support  # noqa: F401

from app.services.live_events import _call_webhook_payload


class LiveCallWebhookTests(TestCase):
    def test_outbound_dial_begin_payload(self):
        payload = _call_webhook_payload(
            "DialBegin",
            {
                "Channel": "PJSIP/1001-00000010",
                "DestChannel": "PJSIP/icc-00000011",
                "Context": "from-internal-trunks",
                "CallerIDNum": "1001",
                "DialString": "01911419050@icc",
                "Uniqueid": "1750835000.10",
                "Linkedid": "1750835000.10",
            },
        )

        self.assertEqual(payload["event"], "call.dialing")
        self.assertEqual(payload["direction"], "outbound")
        self.assertEqual(payload["caller"], "1001")
        self.assertEqual(payload["callee"], "01911419050")
        self.assertEqual(payload["agent_extension"], "1001")
        self.assertEqual(payload["trunk"], "icc")

    def test_inbound_dial_begin_payload(self):
        payload = _call_webhook_payload(
            "DialBegin",
            {
                "Channel": "PJSIP/icc-00000011",
                "DestChannel": "PJSIP/1001-00000012",
                "Context": "from-trunk-icc",
                "CallerIDNum": "01711111111",
                "Exten": "s",
                "Uniqueid": "1750835000.11",
                "Linkedid": "1750835000.11",
            },
        )

        self.assertEqual(payload["event"], "call.ringing")
        self.assertEqual(payload["direction"], "inbound")
        self.assertEqual(payload["caller"], "01711111111")
        self.assertEqual(payload["callee"], "1001")
        self.assertEqual(payload["agent_extension"], "1001")
        self.assertEqual(payload["trunk"], "icc")

    def test_ignores_non_ringing_newstate(self):
        self.assertIsNone(
            _call_webhook_payload(
                "Newstate",
                {
                    "Channel": "PJSIP/1001-00000010",
                    "ChannelStateDesc": "Down",
                    "Uniqueid": "1750835000.10",
                },
            )
        )
