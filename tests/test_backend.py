"""Backend unit and integration tests with no real external API calls."""
import hashlib
import hmac
import json
import os
import sys
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, Session, create_engine, select

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

os.environ.setdefault("WEBHOOK_HMAC_SECRET", "test-secret-32chars-aaaaaaaaaaaa")
os.environ.setdefault("DATABASE_URL", "sqlite:///./test_alerts.db")
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "")
os.environ.setdefault("TELEGRAM_CHAT_ID", "")

from api import signal as signal_api
from core.security import verify_hmac
from db.database import get_session
from models.alert import Alert
from services.llm.prompts import SYSTEM_PROMPT, build_user_prompt
from services.news import aggregator
from services.news.forex_factory import NewsEvent, is_red_news_imminent
from services.telegram.formatter import format_alert, format_no_go_news

SECRET = "test-secret-32chars-aaaaaaaaaaaa"

SAMPLE_SIGNAL = {
    "id": "abc-123",
    "timestamp": "2026-06-20T09:30:00+00:00",
    "symbol": "EURUSD",
    "setup": "london_judas",
    "direction": "long",
    "pattern": "Asian high sweep + CHoCH",
    "entry": 1.0850,
    "sl": 1.0840,
    "tp1": 1.0860,
    "tp_final": 1.0870,
    "killzone": "LONDON",
    "killzone_match": True,
    "meta": {"confluence_tags": ["sweep_asian_high", "choch_m5"]},
}

SAMPLE_VERDICT = {
    "verdict": "GO",
    "impact_level": "LOW",
    "reason_short": "Macro neutre et aucune news imminente.",
    "risk_main": "Retournement du DXY",
    "action": "Surveiller le retest avant entrée",
}

NO_NEWS = {
    "red_news_imminent": False,
    "upcoming_events": [],
    "macro": "DXY stable",
    "macro_alignment": {"macro_alignment": "NEUTRAL", "detail": ""},
}


@pytest.fixture
def backend_client(monkeypatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    app = FastAPI()
    app.include_router(signal_api.router)

    def override_session():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    monkeypatch.setattr(signal_api.settings, "HARD_BLOCK_RED_NEWS", False)
    monkeypatch.setattr(signal_api.settings, "BLOCK_ORANGE_NEWS", False)
    monkeypatch.setattr(signal_api, "get_news_context", lambda **_: dict(NO_NEWS))
    monkeypatch.setattr(signal_api, "get_verdict", lambda *_: (dict(SAMPLE_VERDICT), "groq"))
    monkeypatch.setattr(signal_api, "send_message", lambda _text: 42)
    return TestClient(app), engine


def _post_signal(client: TestClient, signal: dict = SAMPLE_SIGNAL):
    body = json.dumps(signal).encode()
    signature = hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()
    return client.post("/signal", content=body, headers={"X-HMAC-Signature": signature})


def _only_alert(engine) -> Alert:
    with Session(engine) as session:
        return session.exec(select(Alert)).one()


def test_hmac_valid():
    payload = b'{"setup": "london_judas"}'
    sig = hmac.new(SECRET.encode(), payload, hashlib.sha256).hexdigest()
    assert verify_hmac(payload, sig) is True


def test_hmac_invalid():
    assert verify_hmac(b'{"setup": "london_judas"}', "bad-signature") is False


def test_hmac_tampered_payload():
    payload = b'{"setup": "london_judas"}'
    sig = hmac.new(SECRET.encode(), payload, hashlib.sha256).hexdigest()
    assert verify_hmac(b'{"setup": "ote_continuation"}', sig) is False


def test_formatter_reads_new_schema():
    msg = format_alert(SAMPLE_SIGNAL, SAMPLE_VERDICT, "groq", NO_NEWS)
    for expected in ("london_judas", "1.08500", "1.08400", "1.08600", "1.08700"):
        assert expected in msg
    assert "Verdict: GO · Impact: LOW" in msg
    assert "RR 2.00" in msg


def test_format_alert_no_verdict():
    assert "Analyse LLM indisponible" in format_alert(SAMPLE_SIGNAL, None, "none", NO_NEWS)


def test_format_no_go_news():
    msg = format_no_go_news(SAMPLE_SIGNAL, "NFP")
    assert "BLOQUÉ" in msg
    assert "NFP" in msg


def _make_event(impact: str, minutes_ahead: float, currency: str = "USD") -> NewsEvent:
    return NewsEvent(
        time_utc=datetime.now(tz=timezone.utc) + timedelta(minutes=minutes_ahead),
        currency=currency,
        impact=impact,  # type: ignore[arg-type]
        title=f"Test {impact} event",
    )


def test_red_news_imminent_within_window():
    assert is_red_news_imminent([_make_event("red", 10)], 15) is True


def test_red_news_not_imminent_outside_window():
    assert is_red_news_imminent([_make_event("red", 20)], 15) is False


def test_non_watched_red_not_kill_switch():
    assert is_red_news_imminent([_make_event("red", 5, "JPY")], 15) is False


def test_eur_event_included_in_context(monkeypatch):
    event = _make_event("red", 5, "EUR")
    with aggregator._lock:
        old_cache = dict(aggregator._cache)
        aggregator._cache.update(
            events=[event], macro=None, updated_at=datetime.now(tz=timezone.utc)
        )
    try:
        context = aggregator.get_news_context(window_minutes=60, direction="long")
    finally:
        with aggregator._lock:
            aggregator._cache.update(old_cache)
    assert context["upcoming_events"][0]["currency"] == "EUR"
    assert context["red_news_imminent"] is True


def test_prompt_contains_eurusd_impact_contract():
    prompt = build_user_prompt(SAMPLE_SIGNAL, NO_NEWS)
    assert "EURUSD" in SYSTEM_PROMPT
    assert "ECB" in SYSTEM_PROMPT and "FOMC" in SYSTEM_PROMPT
    assert "impact_level" in prompt
    assert all(level in prompt for level in ("HIGH", "MODERATE", "LOW"))


def test_signal_new_schema_persisted(backend_client):
    client, engine = backend_client
    response = _post_signal(client)
    assert response.status_code == 202
    alert = _only_alert(engine)
    assert (alert.setup, alert.entry, alert.sl, alert.tp1, alert.tp_final) == (
        "london_judas", 1.0850, 1.0840, 1.0860, 1.0870
    )
    assert not hasattr(alert, "tier")
    assert not hasattr(alert, "entry_zone_low")


def test_signal_always_sent_even_on_no_go(backend_client, monkeypatch):
    client, _ = backend_client
    no_go = {**SAMPLE_VERDICT, "verdict": "NO_GO", "impact_level": "MODERATE"}
    monkeypatch.setattr(signal_api, "get_verdict", lambda *_: (no_go, "groq"))
    body = _post_signal(client).json()
    assert body["status"] == "ok"
    assert body["telegram_sent"] is True


def test_red_news_annotates_not_blocks_by_default(backend_client, monkeypatch):
    client, _ = backend_client
    sent = []
    red_context = {**NO_NEWS, "red_news_imminent": True}
    monkeypatch.setattr(signal_api, "get_news_context", lambda **_: red_context)
    monkeypatch.setattr(signal_api, "send_message", lambda text: sent.append(text) or 43)
    body = _post_signal(client).json()
    assert body["status"] == "ok"
    assert "🔴 News rouge imminente" in sent[0]


def test_red_news_blocks_when_hard_flag_on(backend_client, monkeypatch):
    client, _ = backend_client
    monkeypatch.setattr(signal_api.settings, "HARD_BLOCK_RED_NEWS", True)
    monkeypatch.setattr(
        signal_api,
        "get_news_context",
        lambda **_: {**NO_NEWS, "red_news_imminent": True},
    )
    body = _post_signal(client).json()
    assert body["status"] == "blocked"
    assert body["reason"] == "red_news_kill_switch"


def test_impact_level_persisted(backend_client, monkeypatch):
    client, engine = backend_client
    verdict = {**SAMPLE_VERDICT, "impact_level": "HIGH"}
    monkeypatch.setattr(signal_api, "get_verdict", lambda *_: (verdict, "groq"))
    _post_signal(client)
    assert _only_alert(engine).llm_impact_level == "HIGH"


def test_llm_down_still_sends(backend_client, monkeypatch):
    client, engine = backend_client
    sent = []
    monkeypatch.setattr(signal_api, "get_verdict", lambda *_: (None, "none"))
    monkeypatch.setattr(signal_api, "send_message", lambda text: sent.append(text) or 44)
    body = _post_signal(client).json()
    assert body["status"] == "ok"
    assert body["telegram_sent"] is True
    assert "Analyse LLM indisponible" in sent[0]
    assert _only_alert(engine).telegram_sent is True


sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "detector"))
from webhook import _sign as detector_sign


def test_detector_sign_matches_backend_verify():
    payload = json.dumps(SAMPLE_SIGNAL, default=str, sort_keys=True).encode()
    assert verify_hmac(payload, detector_sign(payload, SECRET)) is True
