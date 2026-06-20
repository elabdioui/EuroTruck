from datetime import datetime, timezone
from typing import Optional

from sqlmodel import Field, SQLModel


class Alert(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    signal_id: str = Field(index=True)
    received_at: datetime = Field(default_factory=lambda: datetime.now(tz=timezone.utc))
    symbol: str = "EURUSD"

    setup: str
    direction: str
    pattern: str
    killzone: str = ""
    killzone_match: bool = False

    entry: float
    sl: float
    tp1: float
    tp_final: float

    signal_json: str
    news_context: str = ""

    llm_verdict: str = ""
    llm_impact_level: str = ""
    llm_reasoning: str = ""
    llm_risk: str = ""
    llm_action: str = ""
    llm_provider: str = ""

    telegram_sent: bool = False
    telegram_message_id: Optional[int] = None
    error: Optional[str] = None
