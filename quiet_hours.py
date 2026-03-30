"""Quiet hours detection for Barkomatic Sentinel."""
from datetime import datetime, time as dt_time
from zoneinfo import ZoneInfo


def _parse_time(t_str: str) -> dt_time:
    """Parse 'HH:MM' into a time object."""
    parts = t_str.strip().split(":")
    return dt_time(int(parts[0]), int(parts[1]))


def _is_in_window(ts: datetime, start: dt_time, end: dt_time) -> bool:
    """Return True if ts.time() falls within the quiet window.

    Handles overnight windows (e.g. 22:00–08:00) where start > end.
    """
    t = ts.timetz().replace(tzinfo=None).replace(microsecond=0)
    t = dt_time(t.hour, t.minute, t.second)
    if start <= end:
        return start <= t < end
    # Overnight wrap: e.g. 22:00–08:00
    return t >= start or t < end


def is_quiet_hours(timestamp_str: str, config) -> bool:
    """Return True if the given ISO8601/SQLite timestamp falls within quiet hours.

    Args:
        timestamp_str: Timestamp string in ISO8601 or SQLite format.
        config: Config class (or any object with QUIET_HOURS_ENABLED,
                QUIET_HOURS_WEEKDAY, QUIET_HOURS_WEEKEND, LOCAL_TIMEZONE).

    Returns:
        True if quiet hours are enabled and the timestamp is within the window.
    """
    if not getattr(config, "QUIET_HOURS_ENABLED", False):
        return False

    # Parse timestamp
    ts = None
    for fmt in (
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S %Z",
        "%Y-%m-%d %H:%M:%S",
    ):
        try:
            ts = datetime.strptime(timestamp_str.strip(), fmt)
            break
        except (ValueError, AttributeError):
            continue

    if ts is None:
        return False

    # Localise if naive
    try:
        tz = ZoneInfo(getattr(config, "LOCAL_TIMEZONE", "UTC"))
    except Exception:
        tz = ZoneInfo("UTC")

    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=tz)
    else:
        ts = ts.astimezone(tz)

    # isoweekday: 1=Monday … 7=Sunday; 5=Saturday, 6=Sunday (0-indexed weekday: 5,6)
    is_weekend = ts.weekday() >= 5  # Saturday=5, Sunday=6

    window = config.QUIET_HOURS_WEEKEND if is_weekend else config.QUIET_HOURS_WEEKDAY

    try:
        start = _parse_time(window["start"])
        end = _parse_time(window["end"])
    except (KeyError, ValueError, TypeError):
        return False

    return _is_in_window(ts, start, end)
