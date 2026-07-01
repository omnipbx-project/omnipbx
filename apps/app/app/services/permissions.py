from __future__ import annotations

import json

import psycopg
from psycopg.rows import dict_row


ALL_FEATURES = {
    "admin_accounts:manage", "admin_accounts:view",
    "api_push:manage", "api_push:send_test", "api_push:view",
    "audit_log:view",
    "backup_restore:backup", "backup_restore:restore", "backup_restore:view",
    "call_logs:export", "call_logs:recordings", "call_logs:view",
    "call_records:download", "call_records:view",
    "call_routing:manage", "call_routing:view",
    "callbacks:complete", "callbacks:take", "callbacks:view",
    "dashboard:view",
    "groups:manage", "groups:view",
    "inbound_routes:manage", "inbound_routes:view",
    "ivrs:manage", "ivrs:view",
    "live_overview:supervise", "live_overview:view",
    "permissions:manage", "permissions:view",
    "queues:manage", "queues:view",
    "reports:export", "reports:view",
    "ring_groups:manage", "ring_groups:view",
    "settings:manage", "settings:view",
    "softphone:configure", "softphone:provision", "softphone:view",
    "status:run_checks", "status:view",
    "trunks:manage", "trunks:test", "trunks:view",
    "users:create", "users:delete", "users:edit", "users:view",
    "voicemail:delete", "voicemail:manage", "voicemail:view",
    "working_hours:manage", "working_hours:view",
}

BUILTIN_PERMISSION_FEATURES = {
    "User": {
        "dashboard:view",
        "live_overview:view",
        "softphone:view",
    },
    "Supervisor": {
        "dashboard:view",
        "live_overview:view",
        "live_overview:supervise",
        "users:view",
        "call_logs:view",
        "callbacks:view",
        "callbacks:take",
        "callbacks:complete",
        "call_records:view",
        "reports:view",
        "softphone:view",
    },
    "Admin": ALL_FEATURES,
}

NAV_FEATURES = {
    "/dashboard": "dashboard:view",
    "/live-overview": "live_overview:view",
    "/extensions": "users:view",
    "/trunks": "trunks:view",
    "/call-routing": "call_routing:view",
    "/call-routing/auto-dialer/leads": "call_routing:view",
    "/call-logs": "call_logs:view",
    "/callbacks": "callbacks:view",
    "/call-records": "call_records:view",
    "/welcome-messages": "voicemail:view",
    "/reports": "reports:view",
    "/settings": "settings:view",
    "/status": "status:view",
    "/api-push": "api_push:view",
}


def features_for_principal(connection: psycopg.Connection, principal: dict | None) -> set[str]:
    if not principal:
        return set()
    if principal.get("role") != "user":
        return set(ALL_FEATURES)

    extension = str(principal.get("extension") or principal.get("username") or "").strip()
    if not extension:
        return set()
    with connection.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT
                COALESCE(permission.name, group_permission.name, 'User') AS permission_name,
                COALESCE(permission.features, group_permission.features, '[]'::jsonb) AS features
            FROM extensions extension_row
            LEFT JOIN user_profiles profile ON profile.extension = extension_row.extension
            LEFT JOIN user_permissions permission ON permission.id = profile.permission_id
            LEFT JOIN user_groups group_row ON group_row.id = profile.group_id
            LEFT JOIN user_permissions group_permission ON group_permission.id = group_row.permission_id
            WHERE extension_row.extension = %(extension)s
            """,
            {"extension": extension},
        )
        row = cursor.fetchone()
    if not row:
        return set()
    features = _normalize_features(row.get("features"))
    if any(":" in feature for feature in features):
        return {feature for feature in features if feature in ALL_FEATURES}
    return set(BUILTIN_PERMISSION_FEATURES.get(str(row.get("permission_name") or "User"), set()))


def has_feature(features: set[str], required: str) -> bool:
    return required in features


def filter_navigation(nav_sections: list[dict], features: set[str]) -> list[dict]:
    filtered: list[dict] = []
    for section in nav_sections:
        items = [
            dict(item)
            for item in section["items"]
            if NAV_FEATURES.get(item["href"]) in features
        ]
        if items:
            filtered.append({**section, "items": items})
    return filtered


def first_allowed_path(features: set[str]) -> str:
    for path, feature in NAV_FEATURES.items():
        if feature in features:
            return path
    if "softphone:view" in features:
        return "/softphone"
    return "/my-profile"


def required_feature(method: str, path: str) -> str | None:
    method = method.upper()
    write = method not in {"GET", "HEAD", "OPTIONS"}

    if path in {"/", "/logout"} or path.startswith("/my-profile") or path.startswith("/user-photos"):
        return None
    if path.startswith("/dashboard"):
        return "dashboard:view"
    if path.startswith("/live-overview/supervisor-action"):
        return "live_overview:supervise"
    if path.startswith("/live-overview"):
        return "live_overview:view"
    if path.startswith("/api/extensions"):
        return "users:view" if not write else ("users:delete" if method == "DELETE" else "users:create")
    if path.startswith("/extensions/permissions"):
        return "permissions:manage" if write else "permissions:view"
    if path.startswith("/extensions/groups"):
        return "groups:manage" if write else "groups:view"
    if path.startswith("/extensions"):
        if not write:
            return "users:view"
        if path.endswith("/delete"):
            return "users:delete"
        if path.endswith("/create"):
            return "users:create"
        return "users:edit"
    if path.startswith("/api/trunks") or path.startswith("/trunks"):
        if not write:
            return "trunks:view"
        return "trunks:test" if path.endswith("/test") or path == "/trunks/test" else "trunks:manage"
    if path.startswith("/call-routing"):
        return "call_routing:manage" if write else "call_routing:view"
    if path.startswith("/api/inbound-routes") or path.startswith("/inbound-routes"):
        return "inbound_routes:manage" if write else "inbound_routes:view"
    if path.startswith("/api/ring-groups") or path.startswith("/ring-groups"):
        return "ring_groups:manage" if write else "ring_groups:view"
    if path.startswith("/api/queues") or path.startswith("/queues"):
        return "queues:manage" if write else "queues:view"
    if path.startswith("/api/ivrs") or path.startswith("/ivrs"):
        return "ivrs:manage" if write else "ivrs:view"
    if path.startswith("/api/working-hours") or path.startswith("/working-hours"):
        return "working_hours:manage" if write else "working_hours:view"
    if path.startswith("/api/call-recordings"):
        return "call_logs:recordings"
    if path.startswith("/api/call-logs") or path.startswith("/call-logs"):
        if path.endswith("/export"):
            return "call_logs:export"
        return "call_logs:view"
    if path.startswith("/api/callbacks") or path.startswith("/callbacks"):
        if path.endswith("/take"):
            return "callbacks:take"
        if path.endswith("/done"):
            return "callbacks:complete"
        return "callbacks:view"
    if path.startswith("/call-records"):
        return "call_records:download" if "download" in path else "call_records:view"
    if path.startswith("/voicemail/messages"):
        return "voicemail:delete" if write else "voicemail:view"
    if path.startswith("/api/welcome-messages") or path.startswith("/welcome-messages"):
        return "voicemail:manage" if write else "voicemail:view"
    if path.startswith("/reports/export"):
        return "reports:export"
    if path.startswith("/reports"):
        return "reports:view"
    if path.startswith("/audit-log"):
        return "audit_log:view"
    if path.startswith("/settings"):
        return "settings:manage" if write else "settings:view"
    if path.startswith("/status/usage"):
        return "dashboard:view"
    if path.startswith("/status"):
        return "status:run_checks" if write else "status:view"
    if path.startswith("/backup-restore"):
        if not write:
            return "backup_restore:view"
        return "backup_restore:restore" if path.endswith("/restore") else "backup_restore:backup"
    if path.startswith("/api-push"):
        if not write:
            return "api_push:view"
        return "api_push:send_test" if "test" in path or path.endswith("/run") else "api_push:manage"
    if path.startswith("/admin-accounts"):
        return "admin_accounts:manage" if write else "admin_accounts:view"
    if path == "/api/softphone/bootstrap":
        return "softphone:configure"
    if path == "/softphone":
        return "softphone:configure"
    if path.startswith("/api/softphone/settings") or path.startswith("/softphone/settings"):
        return "softphone:configure"
    if path.startswith("/softphone/extension/download"):
        return "softphone:provision"
    if path.startswith("/api/softphone") or path.startswith("/softphone") or path.startswith("/webphone"):
        return "softphone:view"
    if path.startswith("/api/system/update"):
        return "settings:manage" if write else "settings:view"
    if path.startswith("/api/system"):
        return "status:run_checks" if write else "status:view"
    return ""


def _normalize_features(value) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return []
        if isinstance(parsed, list):
            return [str(item).strip() for item in parsed if str(item).strip()]
    return []
