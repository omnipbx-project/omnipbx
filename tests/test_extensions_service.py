from unittest import TestCase

import support  # noqa: F401

from app.services.extensions import (
    ADMIN_EXTENSION,
    SOFTPHONE_TRANSPORT,
    WEBPHONE_TRANSPORT,
    audio_codecs_for_transport,
    auto_provision_enabled_for_transport,
    delete_extension,
    normalize_simultaneous_device_limit,
    pjsip_transport_for_device,
    update_extension_user,
    video_codecs_for_transport,
)


class ExtensionServiceTests(TestCase):
    def test_transport_helpers_return_expected_codec_and_provisioning_defaults(self):
        self.assertEqual(audio_codecs_for_transport(WEBPHONE_TRANSPORT), "ulaw,alaw,opus")
        self.assertEqual(video_codecs_for_transport(WEBPHONE_TRANSPORT), "")
        self.assertEqual(audio_codecs_for_transport(SOFTPHONE_TRANSPORT), "ulaw,alaw,opus")
        self.assertEqual(video_codecs_for_transport(SOFTPHONE_TRANSPORT), "")
        self.assertEqual(audio_codecs_for_transport("transport-udp"), "ulaw,alaw,opus")
        self.assertEqual(video_codecs_for_transport("transport-udp"), "")
        self.assertTrue(auto_provision_enabled_for_transport(WEBPHONE_TRANSPORT))
        self.assertFalse(auto_provision_enabled_for_transport("transport-udp"))
        self.assertEqual(pjsip_transport_for_device(WEBPHONE_TRANSPORT), "transport-wss")
        self.assertEqual(pjsip_transport_for_device(SOFTPHONE_TRANSPORT), "transport-udp")

    def test_simultaneous_device_limit_is_clamped_and_fallback_safe(self):
        self.assertEqual(normalize_simultaneous_device_limit("0"), 1)
        self.assertEqual(normalize_simultaneous_device_limit("6"), 6)
        self.assertEqual(normalize_simultaneous_device_limit("99"), 10)
        self.assertEqual(normalize_simultaneous_device_limit("not-a-number"), 1)

    def test_admin_extension_cannot_be_deleted_or_renumbered(self):
        with self.assertRaises(ValueError):
            delete_extension(object(), ADMIN_EXTENSION)

        with self.assertRaises(ValueError):
            update_extension_user(
                object(),
                ADMIN_EXTENSION,
                "10001",
                "Owner",
                "transport-udp",
                True,
                1,
            )
