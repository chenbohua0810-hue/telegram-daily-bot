from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo


def next_daily_run(*, now_utc: datetime, hour: int, minute: int, timezone_name: str) -> datetime:
    if now_utc.tzinfo is None:
        raise ValueError("now_utc must be timezone-aware")
    tz = ZoneInfo(timezone_name)
    local_now = now_utc.astimezone(tz)
    candidate = local_now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if candidate <= local_now:
        candidate = candidate.replace(day=local_now.day)  # explicit for readability
        candidate = candidate + _one_day()
    return candidate


def seconds_until(target: datetime, *, now_utc: datetime | None = None) -> float:
    now = now_utc or datetime.now(timezone.utc)
    return max(0.0, (target.astimezone(timezone.utc) - now.astimezone(timezone.utc)).total_seconds())


def _one_day():
    from datetime import timedelta

    return timedelta(days=1)
