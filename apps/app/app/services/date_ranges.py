from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


DATE_RANGE_OPTIONS = [
    {"key": "today", "label": "Today"},
    {"key": "yesterday", "label": "Yesterday"},
    {"key": "7d", "label": "Last 7 days"},
    {"key": "last_week", "label": "Last week"},
    {"key": "30d", "label": "Last 30 Days"},
    {"key": "this_month", "label": "This month"},
    {"key": "last_month", "label": "Last month"},
    {"key": "this_year", "label": "This year"},
    {"key": "all", "label": "All time"},
    {"key": "custom", "label": "Custom"},
]


@dataclass(frozen=True)
class ResolvedDateRange:
    key: str
    date_from: str
    date_to: str
    is_custom: bool


def valid_range_key(value: str | None, *, default: str = "7d") -> str:
    keys = {item["key"] for item in DATE_RANGE_OPTIONS}
    return value if value in keys else default


def resolve_date_range(
    range_key: str | None,
    *,
    date_from: str = "",
    date_to: str = "",
    default: str = "7d",
    timezone_name: str = "UTC",
) -> ResolvedDateRange:
    key = valid_range_key(range_key, default=default)
    if key == "custom":
        return ResolvedDateRange(key=key, date_from=_clean_date(date_from), date_to=_clean_date(date_to), is_custom=True)
    if key == "all":
        return ResolvedDateRange(key=key, date_from="", date_to="", is_custom=False)

    today = datetime.now(_timezone(timezone_name)).date()
    if key == "today":
        start = end = today
    elif key == "yesterday":
        start = end = today - timedelta(days=1)
    elif key == "last_week":
        this_week_start = today - timedelta(days=today.weekday())
        start = this_week_start - timedelta(days=7)
        end = this_week_start - timedelta(days=1)
    elif key == "30d":
        start = today - timedelta(days=29)
        end = today
    elif key == "this_month":
        start = today.replace(day=1)
        end = today
    elif key == "last_month":
        this_month_start = today.replace(day=1)
        end = this_month_start - timedelta(days=1)
        start = end.replace(day=1)
    elif key == "this_year":
        start = today.replace(month=1, day=1)
        end = today
    else:
        start = today - timedelta(days=6)
        end = today
        key = "7d"
    return ResolvedDateRange(key=key, date_from=start.isoformat(), date_to=end.isoformat(), is_custom=False)


def date_range_context(
    range_key: str | None,
    *,
    date_from: str = "",
    date_to: str = "",
    default: str = "7d",
    timezone_name: str = "UTC",
) -> dict[str, object]:
    resolved = resolve_date_range(range_key, date_from=date_from, date_to=date_to, default=default, timezone_name=timezone_name)
    return {
        "options": DATE_RANGE_OPTIONS,
        "active": resolved.key,
        "date_from": resolved.date_from,
        "date_to": resolved.date_to,
        "is_custom": resolved.is_custom,
    }


def parse_date_bound(value: str, *, end_of_day: bool, timezone_name: str = "UTC") -> datetime | None:
    cleaned = (value or "").strip()
    if not cleaned:
        return None
    local_tz = _timezone(timezone_name)
    if "T" in cleaned:
        try:
            parsed = datetime.fromisoformat(cleaned)
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=local_tz)
        return parsed.astimezone(UTC)
    try:
        parsed_date = date.fromisoformat(cleaned)
    except ValueError:
        return None
    parsed_time = time.max.replace(microsecond=0) if end_of_day else time.min
    return datetime.combine(parsed_date, parsed_time, tzinfo=local_tz).astimezone(UTC)


def _clean_date(value: str) -> str:
    cleaned = (value or "").strip()
    if not cleaned:
        return ""
    if "T" in cleaned:
        try:
            return datetime.fromisoformat(cleaned).strftime("%Y-%m-%dT%H:%M")
        except ValueError:
            return ""
    try:
        return date.fromisoformat(cleaned).isoformat()
    except ValueError:
        return ""


def _timezone(timezone_name: str) -> ZoneInfo:
    try:
        return ZoneInfo((timezone_name or "UTC").strip() or "UTC")
    except ZoneInfoNotFoundError:
        return ZoneInfo("UTC")
