from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from enum import StrEnum


class DateMaxMode(StrEnum):
    DOCUMENTED_EXCLUSIVE = "documented_exclusive"
    OBSERVED_INCLUSIVE = "observed_inclusive_workaround"


def normalize_cfpb_date(value: str | None) -> str | None:
    """Normalize CFPB date-time values to UTC calendar dates."""

    if value is None:
        return None
    raw = value.strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return date.fromisoformat(raw).isoformat()
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).date().isoformat()


def api_date_received_max(end_exclusive: date, *, mode: DateMaxMode) -> date:
    """Translate an internal half-open interval to the observed API boundary."""

    if mode == DateMaxMode.DOCUMENTED_EXCLUSIVE:
        return end_exclusive
    if mode == DateMaxMode.OBSERVED_INCLUSIVE:
        return end_exclusive - timedelta(days=1)
    raise ValueError(f"unsupported date max mode: {mode}")
