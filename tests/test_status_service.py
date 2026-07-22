from unittest import TestCase

import support  # noqa: F401

from app.features.status.service import derive_status, parse_endpoint_output


class StatusServiceTests(TestCase):
    def test_restored_nonqualified_contact_is_online(self):
        output = """
 Endpoint:  300/300                                              Not in use    0 of inf
      Contact:  300/sip:300@192.168.21.101:20223           c9ea2dd075 NonQual         nan
  Transport:  transport-udp             udp      3     96  0.0.0.0:5060
"""

        endpoint = parse_endpoint_output(output)["300"]

        self.assertEqual(endpoint["contact_status"], "NonQual")
        self.assertEqual(
            derive_status(
                endpoint["endpoint_state"],
                endpoint["contact_status"],
                transport=endpoint["transport"],
                contact_uri=endpoint["contact_uri"],
            ),
            "Online",
        )

    def test_unavailable_contact_remains_offline(self):
        self.assertEqual(
            derive_status(
                "Unavailable",
                "Unavail",
                transport="transport-udp",
                contact_uri="300/sip:300@192.168.21.101:20223",
            ),
            "Offline",
        )
