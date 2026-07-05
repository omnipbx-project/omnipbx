from unittest import TestCase
from unittest.mock import patch

import support  # noqa: F401

from app.services.softphone import ice_servers_from_settings


class SoftphoneIceServerTests(TestCase):
    def test_ice_servers_from_settings_builds_stun_and_turn_entries(self):
        servers = ice_servers_from_settings(
            {
                "stun_urls": "stun:turn.example.com:3478, stun:backup.example.com:3478",
                "turn_urls": "turn:turn.example.com:3478\nturns:turn.example.com:5349",
                "turn_username": "agent",
                "turn_credential": "secret",
            }
        )

        self.assertEqual(
            servers,
            [
                {"urls": ["stun:turn.example.com:3478", "stun:backup.example.com:3478"]},
                {
                    "urls": ["turn:turn.example.com:3478", "turns:turn.example.com:5349"],
                    "username": "agent",
                    "credential": "secret",
                },
            ],
        )

    def test_ice_servers_from_settings_ignores_invalid_urls(self):
        servers = ice_servers_from_settings({"stun_urls": "https://example.com\nstun:ok.example.com:3478"})

        self.assertEqual(servers, [{"urls": "stun:ok.example.com:3478"}])

    def test_ice_servers_from_settings_uses_turn_defaults_when_credentials_exist(self):
        with patch("app.services.softphone.get_settings") as get_settings:
            get_settings.return_value.turn_port = 3478
            get_settings.return_value.turn_username = "omnipbx"
            get_settings.return_value.turn_credential = "generated-secret"

            servers = ice_servers_from_settings({}, fallback_host="pbx.example.com")

        self.assertEqual(
            servers,
            [
                {"urls": "stun:pbx.example.com:3478"},
                {
                    "urls": "turn:pbx.example.com:3478",
                    "username": "omnipbx",
                    "credential": "generated-secret",
                },
            ],
        )
