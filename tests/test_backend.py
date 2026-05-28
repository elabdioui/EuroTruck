"""Unit tests for backend — no real API calls."""
import hashlib
import hmac
import json
import sys
import os
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

os.environ.setdefault("WEBHOOK_HMAC_SECRET", "test-secret-32chars-aaaaaaaaaaaa")
os.environ.setdefault("DATABASE_URL", "sqlite:///./test_alerts.db")
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "")
os.environ.setdefault("TELEGRAM_CHAT_ID", "")


# ── Security tests ─────────────────────────────────────────────────────────────

from core.security import verify_hmac

SECRET = "test-secret-32chars-aaaaaaaaaaaa"


def test_hmac_valid():
    payload = b'{"tier": "S"}'
    sig = hmac.new(SECRET.encode(), payload, hashlib.sha256).hexdigest()
    assert verify_hmac(payload, sig) is True


def test_hmac_invalid():
    payload = b'{"tier": "S"}'
    assert verify_hmac(payload, "bad-signature") is False


def test_hmac_tampered_payload():
    payload = b'{"tier": "S"}'
    sig = hmac.new(SECRET.encode(), payload, hashlib.sha256).hexdigest()
    tampered = b'{"tier": "A"}'
    assert verify_hmac(tampered, sig) is False


# ── Formatter tests ────────────────────────────────────────────────────────────

from services.telegram.formatter import format_alert, format_no_go_news

SAMPLE_SIGNAL = {
    "id": "abc-123",
    "timestamp": "2024-01-15T14:30:00+00:00",
    "symbol": "XAUUSD",
    "tier": "S",
    "direction": "LONG",
    "pattern": "Golden Setup",
    "killzone": "NY_AM",
    "entry_zone_low": 1850.50,
    "entry_zone_high": 1852.00,
    "stop_loss": 1845.00,
    "take_profit": 1870.00,
    "bias_h4": "BULLISH",
    "bias_h1": "BULLISH",
    "confluences": ["Bias_H4", "Bias_H1", "SSL_Sweep", "CHoCH_M5", "FVG_M5", "OTE_0.618"],
    "confluence_score": 9,
    "estimated_winrate": 0.72,
}

SAMPLE_VERDICT = {
    "verdict": "GO",
    "reason_short": "Alignement parfait H4/H1, sweep SSL clair",
    "risk_main": "CPI USD dans 45min",
    "action": "Attendre retest FVG 1850.50–1852.00",
}


def test_format_alert_contains_tier():
    msg = format_alert(SAMPLE_SIGNAL, SAMPLE_VERDICT, "gemini")
    assert "TIER S" in msg
    assert "LONG" in msg
    assert "Golden Setup" in msg


def test_format_alert_contains_verdict():
    msg = format_alert(SAMPLE_SIGNAL, SAMPLE_VERDICT, "gemini")
    assert "GO" in msg
    assert "gemini" in msg


def test_format_alert_no_verdict():
    msg = format_alert(SAMPLE_SIGNAL, None, "")
    assert "indisponible" in msg


def test_format_no_go_news():
    msg = format_no_go_news(SAMPLE_SIGNAL, "NFP")
    assert "BLOQUÉ" in msg
    assert "NFP" in msg


# ── News aggregator tests ──────────────────────────────────────────────────────

from services.news.forex_factory import NewsEvent, is_red_news_imminent


def _make_event(impact: str, minutes_ahead: float, currency: str = "USD") -> NewsEvent:
    dt = datetime.now(tz=timezone.utc) + timedelta(minutes=minutes_ahead)
    return NewsEvent(
        time_utc=dt,
        currency=currency,
        impact=impact,  # type: ignore[arg-type]
        title=f"Test {impact} event",
    )


def test_red_news_imminent_within_window():
    events = [_make_event("red", 10)]
    assert is_red_news_imminent(events, window_minutes=15) is True


def test_red_news_not_imminent_outside_window():
    events = [_make_event("red", 20)]
    assert is_red_news_imminent(events, window_minutes=15) is False


def test_orange_news_not_kill_switch():
    events = [_make_event("orange", 5)]
    assert is_red_news_imminent(events, window_minutes=15) is False


def test_non_usd_red_not_kill_switch():
    events = [_make_event("red", 5, currency="EUR")]
    assert is_red_news_imminent(events, window_minutes=15) is False


# ── LLM prompt test ────────────────────────────────────────────────────────────

from services.llm.prompts import build_user_prompt


def test_prompt_contains_signal():
    news_ctx = {
        "red_news_imminent": False,
        "upcoming_us_events": [],
        "macro": "DXY 104.20 (-0.20% 24h)",
    }
    prompt = build_user_prompt(SAMPLE_SIGNAL, news_ctx)
    assert "Golden Setup" in prompt
    assert "DXY" in prompt
    assert "JSON" in prompt


def test_prompt_warns_red_news():
    news_ctx = {
        "red_news_imminent": True,
        "upcoming_us_events": [{"title": "NFP", "impact": "red", "minutes_from_now": 8, "currency": "USD"}],
        "macro": "",
    }
    prompt = build_user_prompt(SAMPLE_SIGNAL, news_ctx)
    assert "OUI" in prompt or "BLOQUE" in prompt
