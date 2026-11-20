"""Value formatting helpers."""

from datetime import datetime, timezone
from functools import lru_cache
from zoneinfo import ZoneInfo

from .. import settings


@lru_cache(maxsize=None)
def display_timezone():
    return ZoneInfo(settings.TIMEZONE)


def now_iso():
    """Current time in UTC, e.g. 2026-10-14T14:45:59+00:00 (stored in SQLite).

    The explicit offset keeps ordering correct across daylight saving time
    changes; strings in this format sort chronologically.
    """

    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def parse_timestamp(value):
    """Stored timestamp -> timezone-aware datetime.

    Values without an offset come from before the UTC migration and are
    local (display time zone) time.
    """

    parsed = datetime.fromisoformat(str(value).strip())

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=display_timezone())

    return parsed


def format_datetime(value):
    """Stored timestamp -> local YYYY-MM-DD HH:MM:SS for display."""

    if value in (None, "", "-"):
        return "-"

    text = str(value).strip()

    try:
        local = parse_timestamp(text).astimezone(display_timezone())
        return local.strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:
        return text.replace("T", " ")


def normalize_value(value):
    """Return a stripped string, or '-' for empty values."""

    if value is None:
        return "-"

    value = str(value).strip()
    return value if value else "-"
