"""News aggregator: combines Forex Factory + macro context, with in-memory cache."""
import json
import logging
from datetime import datetime, timezone
from threading import Lock

from .forex_factory import NewsEvent, fetch_calendar, get_upcoming_events, is_red_news_imminent, is_orange_news_imminent
from .dxy_yields import MacroContext, fetch_macro, macro_alignment
from core.config import settings

log = logging.getLogger(__name__)

_lock = Lock()
_cache: dict = {
    "events": [],
    "macro": None,
    "updated_at": None,
}


def refresh_news() -> None:
    """Called by the scheduler every N minutes."""
    log.info("Refreshing news cache…")
    events = fetch_calendar()
    macro = fetch_macro()
    with _lock:
        _cache["events"] = events
        _cache["macro"] = macro
        _cache["updated_at"] = datetime.now(tz=timezone.utc)
    log.info("News cache refreshed — %d events, macro=%s", len(events), "ok" if macro else "fail")


def get_news_context(window_minutes: int = 60, direction: str | None = None) -> dict:
    """Return a structured news context dict for use in LLM prompts.

    If `direction` ("LONG"/"SHORT") is provided, also include macro_alignment.
    """
    with _lock:
        events: list[NewsEvent] = _cache["events"]
        macro: MacroContext | None = _cache["macro"]
        updated_at = _cache["updated_at"]

    upcoming = get_upcoming_events(events, window_minutes)
    red_imminent = is_red_news_imminent(events, settings.NEWS_RED_BLOCK_WINDOW_MIN)

    upcoming_dicts = [
        {
            "title": e.title,
            "impact": e.impact,
            "minutes_from_now": round(e.minutes_from_now, 1),
            "currency": e.currency,
        }
        for e in upcoming
    ]

    context = {
        "red_news_imminent": red_imminent,
        "upcoming_events": upcoming_dicts,
        "macro": macro.to_prompt_string() if macro else "Macro data unavailable",
        "cache_age_minutes": (
            round((datetime.now(tz=timezone.utc) - updated_at).total_seconds() / 60, 1)
            if updated_at else None
        ),
    }

    if direction is not None:
        context["macro_alignment"] = macro_alignment(direction, macro)

    return context


def is_red_news_kill_switch(window_minutes: int | None = None) -> bool:
    """Hard kill-switch: True if red US news within the configured window.

    BUGFIX: if the cache was never refreshed (updated_at is None), the old code
    returned False (no events => no red news) and the bot traded with NO news
    filter at all. We now block as a precaution when the cache is empty.
    """
    w = window_minutes or settings.NEWS_RED_BLOCK_WINDOW_MIN
    with _lock:
        events: list[NewsEvent] = _cache["events"]
        updated_at = _cache["updated_at"]
    if updated_at is None:
        log.warning("News cache empty (never refreshed) — blocking as precaution")
        return True
    return is_red_news_imminent(events, w)


def is_orange_news_kill_switch(window_minutes: int | None = None) -> bool:
    """Optional kill-switch: True if orange US news within the configured window.
    Only active when BLOCK_ORANGE_NEWS=true in config (default: off)."""
    if not settings.BLOCK_ORANGE_NEWS:
        return False
    w = window_minutes or settings.NEWS_ORANGE_BLOCK_WINDOW_MIN
    with _lock:
        events: list[NewsEvent] = _cache["events"]
    return is_orange_news_imminent(events, w)
