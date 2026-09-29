"""Timezone-safe time helpers.

All timestamps persisted by the engine are UTC and serialised as
``YYYY-MM-DDTHH:MM:SSZ`` so that lexicographic order equals chronological
order (this is what makes SQL ``<= as_of`` filters correct).
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

UTC = timezone.utc
ISO_FMT = "%Y-%m-%dT%H:%M:%SZ"


def utcnow() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)


def ensure_utc(dt: datetime) -> datetime:
    """Return an aware UTC datetime. Naive datetimes are rejected: ambiguity is a bug."""
    if dt.tzinfo is None:
        raise ValueError(f"naive datetime not allowed: {dt!r}")
    return dt.astimezone(UTC)


def iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    return ensure_utc(dt).strftime(ISO_FMT)


def parse_iso(value: str | datetime | None) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return ensure_utc(value)
    s = str(value).strip()
    if not s:
        return None
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        raise ValueError(f"timestamp without timezone: {value!r}")
    return dt.astimezone(UTC)


def local_to_utc(d: date, hhmm: str | None, tz_name: str) -> datetime:
    """Combine a local date and optional ``HH:MM`` into a UTC datetime."""
    tz = ZoneInfo(tz_name)
    if hhmm:
        hh, mm = hhmm.strip().split(":")[:2]
        t = time(int(hh), int(mm))
    else:
        t = time(0, 0)
    return datetime.combine(d, t, tzinfo=tz).astimezone(UTC)


def start_of_local_day_utc(d: date, tz_name: str) -> datetime:
    return datetime.combine(d, time(0, 0), tzinfo=ZoneInfo(tz_name)).astimezone(UTC)


def next_local_midnight_utc(d: date, tz_name: str) -> datetime:
    return start_of_local_day_utc(d + timedelta(days=1), tz_name)


def days_between(a: datetime, b: datetime) -> float:
    return (ensure_utc(b) - ensure_utc(a)).total_seconds() / 86400.0
