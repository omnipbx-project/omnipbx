from unittest import TestCase

import support  # noqa: F401

from app.features.extensions.ui import _safe_return_path
from app.services.permissions import (
    BUILTIN_PERMISSION_FEATURES,
    first_allowed_path,
    filter_navigation,
    required_feature,
)


class PermissionTests(TestCase):
    def test_settings_and_status_require_separate_view_permissions(self):
        self.assertEqual(required_feature("GET", "/settings"), "settings:view")
        self.assertEqual(required_feature("GET", "/status"), "status:view")
        self.assertNotIn("settings:view", BUILTIN_PERMISSION_FEATURES["User"])
        self.assertNotIn("status:view", BUILTIN_PERMISSION_FEATURES["Supervisor"])

    def test_sensitive_actions_require_action_permissions(self):
        self.assertEqual(
            required_feature("POST", "/live-overview/supervisor-action"),
            "live_overview:supervise",
        )
        self.assertEqual(required_feature("POST", "/trunks/icc/test"), "trunks:test")
        self.assertEqual(required_feature("POST", "/call-routing/outgoing-calls/routes/save"), "call_routing:manage")
        self.assertEqual(required_feature("GET", "/api/softphone/bootstrap"), "softphone:configure")
        self.assertEqual(required_feature("GET", "/softphone"), "softphone:configure")
        self.assertEqual(required_feature("GET", "/status/usage"), "dashboard:view")

    def test_navigation_hides_features_without_view_access(self):
        navigation = [
            {
                "title": "Main",
                "items": [
                    {"href": "/dashboard", "label": "Dashboard"},
                    {"href": "/settings", "label": "Settings"},
                    {"href": "/status", "label": "Advanced"},
                ],
            }
        ]

        filtered = filter_navigation(navigation, {"dashboard:view"})

        self.assertEqual([item["href"] for item in filtered[0]["items"]], ["/dashboard"])

    def test_unknown_authenticated_user_routes_are_denied_by_default(self):
        self.assertEqual(required_feature("GET", "/some-new-admin-page"), "")

    def test_first_allowed_path_uses_the_first_visible_feature(self):
        self.assertEqual(first_allowed_path({"softphone:view"}), "/softphone")
        self.assertEqual(first_allowed_path({"call_logs:view"}), "/call-logs")
        self.assertEqual(first_allowed_path(set()), "/my-profile")

    def test_my_profile_is_available_without_a_feature_permission(self):
        self.assertIsNone(required_feature("GET", "/my-profile"))
        self.assertIsNone(required_feature("POST", "/my-profile"))

    def test_profile_return_path_only_accepts_safe_local_pages(self):
        self.assertEqual(_safe_return_path("/extensions"), "/extensions")
        self.assertEqual(_safe_return_path("https://example.com"), "")
        self.assertEqual(_safe_return_path("//example.com"), "")
        self.assertEqual(_safe_return_path("/my-profile"), "")
