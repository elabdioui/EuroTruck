"""Killzone filter — only allow signals during active ICT sessions."""
from datetime import datetime
from typing import Literal
import pytz

from config import cfg

KillzoneName = Literal["LONDON", "NY_AM", "NY_PM"]

# All times in UTC
_KILLZONES_UTC: dict[KillzoneName, tuple[int, int]] = {
    "LONDON": (7, 10),    # 07:00–10:00 UTC
    "NY_AM": (13, 16),    # 13:00–16:00 UTC
    "NY_PM": (18, 20),    # 18:00–20:00 UTC
}


def get_active_killzone(dt: datetime | None = None) -> KillzoneName | None:
    """Return the active killzone name, or None if outside all sessions."""
    if dt is None:
        dt = datetime.now(tz=pytz.utc)
    elif dt.tzinfo is None:
        dt = pytz.utc.localize(dt)

    utc_dt = dt.astimezone(pytz.utc)
    hour = utc_dt.hour

    for name, (start, end) in _KILLZONES_UTC.items():
        if name not in cfg.ENABLED_KILLZONES:
            continue
        if start <= hour < end:
            return name  # type: ignore[return-value]

    return None


def is_in_killzone(dt: datetime | None = None) -> bool:
    return get_active_killzone(dt) is not None


def minutes_to_next_killzone(dt: datetime | None = None) -> int:
    """Return minutes until the next killzone opens (max 24h lookahead)."""
    if dt is None:
        dt = datetime.now(tz=pytz.utc)
    elif dt.tzinfo is None:
        dt = pytz.utc.localize(dt)

    utc = dt.astimezone(pytz.utc)
    current_minutes = utc.hour * 60 + utc.minute
    min_wait = 24 * 60

    for name, (start, _) in _KILLZONES_UTC.items():
        if name not in cfg.ENABLED_KILLZONES:
            continue
        start_minutes = start * 60
        if start_minutes > current_minutes:
            wait = start_minutes - current_minutes
        else:
            wait = (24 * 60 - current_minutes) + start_minutes
        min_wait = min(min_wait, wait)

    return min_wait
