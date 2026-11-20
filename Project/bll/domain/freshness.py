"""Home page: how old a time is, and whether the data is fresh."""

from datetime import datetime, timezone

from ...core.text import parse_timestamp


def minutes_ago(value, now=None):
    """Whole minutes since a stored timestamp, or None when it is not a time."""

    now = now or datetime.now(timezone.utc)
    try:
        return max(0, int((now - parse_timestamp(value)).total_seconds() // 60))
    except (TypeError, ValueError):
        return None


def freshness(minutes):
    """'fresh' (< 10 min), 'late' (< 20), 'stale' or 'unknown'."""

    if minutes is None:
        return "unknown"
    if minutes < 10:
        return "fresh"
    if minutes < 20:
        return "late"
    return "stale"
