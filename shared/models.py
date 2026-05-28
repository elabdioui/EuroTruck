from datetime import datetime
from typing import Literal
from pydantic import BaseModel, Field
import uuid


class Signal(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: datetime
    symbol: str = "XAUUSD"
    tier: Literal["S", "A", "B"]
    direction: Literal["LONG", "SHORT"]
    pattern: str
    killzone: Literal["LONDON", "NY_AM", "NY_PM"]

    entry_zone_low: float
    entry_zone_high: float
    stop_loss: float
    take_profit: float

    bias_h4: Literal["BULLISH", "BEARISH"]
    bias_h1: Literal["BULLISH", "BEARISH"]
    confluences: list[str]

    confluence_score: int
    estimated_winrate: float

    signature: str = ""


class LLMVerdict(BaseModel):
    verdict: Literal["GO", "NO_GO", "WAIT"]
    reason_short: str
    risk_main: str
    action: str
    provider: str = "gemini"
