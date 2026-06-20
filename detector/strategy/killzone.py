"""Killzone filter — only allow signals during active ICT sessions."""
from datetime import datetime
from typing import Literal
import pytz

from config import cfg

KillzoneName = Literal["ASIA", "LONDON", "NY_AM", "NY_PM"]

_NY_TZ = pytz.timezone("America/New_York")

_KILLZONES_NY: dict[KillzoneName, tuple[int, int]] = {
    # (start_minute_of_day, end_minute_of_day) in New York local time
    "ASIA":   (20 * 60,       24 * 60),
    "LONDON": (2 * 60,         5 * 60),
    "NY_AM":  (8 * 60 + 30,   11 * 60),
    "NY_PM":  (13 * 60 + 30,  16 * 60),
}

KILLZONE_PRIORITY: dict[KillzoneName, str] = {
    "LONDON": "primary",
    "NY_AM": "secondary",
    "NY_PM": "secondary",
    "ASIA": "context",
}


def get_active_killzone(dt: datetime | None = None) -> KillzoneName | None:
    """Return the active killzone name, or None if outside all sessions."""
    if dt is None:
        dt = datetime.now(tz=pytz.utc)
    elif dt.tzinfo is None:
        dt = pytz.utc.localize(dt)

    ny = dt.astimezone(_NY_TZ)
    mins = ny.hour * 60 + ny.minute

    for name, (start, end) in _KILLZONES_NY.items():
        if name not in cfg.ENABLED_KILLZONES:
            continue
        if start <= mins < end:
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

    ny = dt.astimezone(_NY_TZ)
    current_minutes = ny.hour * 60 + ny.minute
    min_wait = 24 * 60

    for name, (start_minutes, _) in _KILLZONES_NY.items():
        if name not in cfg.ENABLED_KILLZONES:
            continue
        if start_minutes > current_minutes:
            wait = start_minutes - current_minutes
        else:
            wait = (24 * 60 - current_minutes) + start_minutes
        min_wait = min(min_wait, wait)

    return min_wait
