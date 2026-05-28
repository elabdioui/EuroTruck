"""GET /health and monitoring endpoints."""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlmodel import Session, select, func

from core.security import require_api_token
from db.database import get_session
from models.alert import Alert
from services.news.aggregator import get_news_context

router = APIRouter()


@router.get("/health")
def health():
    return {"status": "ok", "timestamp": datetime.now(tz=timezone.utc).isoformat()}


@router.get("/news/current")
def current_news(_: None = Depends(require_api_token)):
    return get_news_context()


@router.get("/alerts/recent")
def recent_alerts(
    limit: int = 10,
    session: Session = Depends(get_session),
    _: None = Depends(require_api_token),
):
    alerts = session.exec(
        select(Alert).order_by(Alert.received_at.desc()).limit(limit)
    ).all()
    return [
        {
            "id": a.id,
            "tier": a.tier,
            "direction": a.direction,
            "pattern": a.pattern,
            "killzone": a.killzone,
            "received_at": a.received_at.isoformat(),
            "verdict": a.llm_verdict,
            "provider": a.llm_provider,
            "score": a.confluence_score,
            "telegram_sent": a.telegram_sent,
        }
        for a in alerts
    ]


@router.get("/stats/daily")
def daily_stats(
    session: Session = Depends(get_session),
    _: None = Depends(require_api_token),
):
    today = datetime.now(tz=timezone.utc).date()
    alerts = session.exec(
        select(Alert).where(
            func.date(Alert.received_at) == today.isoformat()
        )
    ).all()

    verdicts = [a.llm_verdict for a in alerts]
    return {
        "date": today.isoformat(),
        "total": len(alerts),
        "GO": verdicts.count("GO"),
        "NO_GO": verdicts.count("NO_GO"),
        "WAIT": verdicts.count("WAIT"),
        "no_verdict": verdicts.count(""),
        "tier_s": sum(1 for a in alerts if a.tier == "S"),
        "tier_a": sum(1 for a in alerts if a.tier == "A"),
        "tier_b": sum(1 for a in alerts if a.tier == "B"),
    }
