from datetime import datetime, timedelta, timezone


def as_utc(dt: datetime) -> datetime:
    """Return a timezone-aware UTC datetime.

    SQLite returns SQLAlchemy DateTime(timezone=True) values as naive datetimes.
    The app stores match/deadline times in UTC, so naive values are interpreted
    as UTC before comparisons.
    """
    if dt.tzinfo is None or dt.utcoffset() is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def has_time_passed(dt: datetime) -> bool:
    return utcnow() >= as_utc(dt)


def is_locked_before(dt: datetime, offset: timedelta) -> bool:
    return utcnow() >= as_utc(dt) - offset
