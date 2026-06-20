"""POST /signal — receive and annotate signed EuroTruck webhooks."""
import json
import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session

from core.config import settings
from core.security import require_hmac
from db.database import get_session
from models.alert import Alert
from services.llm.router import get_verdict
from services.news.aggregator import get_news_context
from services.telegram.client import send_message
from services.telegram.formatter import format_alert, format_no_go_news

log = logging.getLogger(__name__)
router = APIRouter()


@router.post("/signal", status_code=202)
async def receive_signal(
    body: bytes = Depends(require_hmac),
    session: Session = Depends(get_session),
):
    try:
        signal = json.loads(body)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    log.info(
        "Signal received — setup=%s dir=%s pattern=%s",
        signal.get("setup"),
        signal.get("direction"),
        signal.get("pattern"),
    )

    news_context = get_news_context(
        window_minutes=60,
        direction=signal.get("direction"),
    )
    red_imminent = bool(news_context.get("red_news_imminent", False))
    orange_imminent = any(
        event.get("impact") == "orange"
        and 0 <= float(event.get("minutes_from_now", 999)) <= settings.NEWS_ORANGE_BLOCK_WINDOW_MIN
        for event in news_context.get("upcoming_events", [])
    )

    if red_imminent and settings.HARD_BLOCK_RED_NEWS:
        return _persist_blocked(
            session,
            signal,
            news_context,
            "red_news_kill_switch",
            "News rouge USD/EUR imminente",
        )

    if orange_imminent and settings.BLOCK_ORANGE_NEWS:
        return _persist_blocked(
            session,
            signal,
            news_context,
            "orange_news_kill_switch",
            "News orange USD/EUR imminente",
        )

    verdict, provider = get_verdict(signal, news_context)
    text = format_alert(signal, verdict, provider, news_context)
    msg_id = send_message(text)

    verdict_str = verdict.get("verdict", "") if verdict else ""
    impact_level = verdict.get("impact_level", "") if verdict else ""
    alert = _build_alert(
        signal,
        news_context,
        verdict_str,
        impact_level,
        verdict.get("reason_short", "") if verdict else "",
        verdict.get("risk_main", "") if verdict else "",
        verdict.get("action", "") if verdict else "",
        provider,
        telegram_sent=msg_id is not None,
        telegram_message_id=msg_id,
    )
    session.add(alert)
    session.commit()
    session.refresh(alert)

    log.info(
        "Alert #%d saved — verdict=%s impact=%s provider=%s tg_sent=%s",
        alert.id,
        verdict_str,
        impact_level,
        provider,
        msg_id is not None,
    )
    return {
        "status": "ok",
        "alert_id": alert.id,
        "verdict": verdict_str,
        "impact_level": impact_level,
        "provider": provider,
        "telegram_sent": msg_id is not None,
    }


def _persist_blocked(
    session: Session,
    signal: dict,
    news_context: dict,
    reason: str,
    message_reason: str,
) -> dict:
    log.warning("Explicit news kill-switch — signal blocked: %s", reason)
    text = format_no_go_news(signal, message_reason)
    msg_id = send_message(text)
    alert = _build_alert(
        signal,
        news_context,
        "NO_GO",
        "HIGH" if reason.startswith("red") else "MODERATE",
        message_reason,
        message_reason,
        "Ne pas entrer en position",
        "none",
        telegram_sent=msg_id is not None,
        telegram_message_id=msg_id,
    )
    session.add(alert)
    session.commit()
    session.refresh(alert)
    return {
        "status": "blocked",
        "alert_id": alert.id,
        "reason": reason,
        "verdict": "NO_GO",
        "impact_level": alert.llm_impact_level,
        "provider": "none",
        "telegram_sent": msg_id is not None,
    }


def _build_alert(
    signal: dict,
    news_context: dict,
    verdict_str: str,
    impact_level: str,
    reasoning: str,
    risk: str,
    action: str,
    provider: str,
    telegram_sent: bool = False,
    telegram_message_id: int | None = None,
    error: str | None = None,
) -> Alert:
    return Alert(
        signal_id=str(signal.get("id") or uuid.uuid4()),
        received_at=datetime.now(tz=timezone.utc),
        symbol=signal.get("symbol", settings.SYMBOL),
        setup=signal.get("setup", "?"),
        direction=signal.get("direction", "?"),
        pattern=signal.get("pattern", "?"),
        killzone=signal.get("killzone", ""),
        killzone_match=bool(signal.get("killzone_match", False)),
        entry=float(signal.get("entry", 0.0)),
        sl=float(signal.get("sl", 0.0)),
        tp1=float(signal.get("tp1", 0.0)),
        tp_final=float(signal.get("tp_final", 0.0)),
        signal_json=json.dumps(signal, default=str),
        news_context=json.dumps(news_context, default=str),
        llm_verdict=verdict_str,
        llm_impact_level=impact_level,
        llm_reasoning=reasoning,
        llm_risk=risk,
        llm_action=action,
        llm_provider=provider,
        telegram_sent=telegram_sent,
        telegram_message_id=telegram_message_id,
        error=error,
    )
