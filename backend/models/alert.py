from datetime import datetime
from typing import Optional
from sqlmodel import SQLModel, Field


class Alert(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    signal_id: str = Field(index=True)
    received_at: datetime = Field(default_factory=datetime.utcnow)
    symbol: str = "XAUUSD"
    tier: str
    direction: str
    pattern: str
    killzone: str

    entry_zone_low: float
    entry_zone_high: float
    stop_loss: float
    take_profit: float
    confluence_score: int

    signal_json: str            # raw payload JSON
    news_context: str = ""      # JSON of scraped news
    llm_verdict: str = ""       # "GO" | "NO_GO" | "WAIT" | ""
    llm_reasoning: str = ""
    llm_risk: str = ""
    llm_action: str = ""
    llm_provider: str = ""

    telegram_sent: bool = False
    telegram_message_id: Optional[int] = None
    error: Optional[str] = None
