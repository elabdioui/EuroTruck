"""Order Block and Breaker Block detection."""
import pandas as pd
from dataclasses import dataclass
from datetime import datetime

from config import Config


@dataclass
class OrderBlock:
    type: str
    top: float
    bottom: float
    mid: float
    time: datetime
    touched: bool = False       # prix entré dans la zone (mèche suffit) → mitigé
    test_count: int = 0         # nombre de tests (invalidation si > 3, cf. SKILL)
    mitigated: bool = False     # conservé pour compat : close au-travers
    is_breaker: bool = False
    breaker_time: datetime | None = None  # when the OB flipped to a breaker
    @property
    def label(self) -> str:
        prefix = "BB" if self.is_breaker else "OB"
        return f"{prefix}_{self.type[0]}"


def detect_order_blocks(df: pd.DataFrame, lookback: int = 30) -> list[OrderBlock]:
    """
    Bullish OB: last BEARISH candle immediately before a bullish displacement.
    Bearish OB: last BULLISH candle immediately before a bearish displacement.
    Displacement = move of at least 1× the OB body size.
    """
    if len(df) < lookback + 5:
        return []

    obs: list[OrderBlock] = []
    used_indices: set[int] = set()

    for i in range(lookback, len(df) - 3):
        candle = df.iloc[i]
        body = abs(candle["close"] - candle["open"])
        if body < Config.OB_MIN_BODY_PIPS * Config.PIP:  # ignore doji
            continue

        is_bearish = candle["close"] < candle["open"]
        is_bullish = candle["close"] > candle["open"]

        # Bullish OB: bearish candle (open > close) before strong bullish move.
        # ICT zone = candle BODY only (open→close), not the full wick range.
        if is_bearish and i not in used_indices:
            next_slice = df.iloc[i + 1 : i + 5]
            displacement = next_slice["high"].max() - candle["high"]
            if displacement >= body:
                obs.append(OrderBlock(
                    type="BULLISH",
                    top=candle["open"],     # body top for a bearish candle
                    bottom=candle["close"], # body bottom for a bearish candle
                    mid=(candle["open"] + candle["close"]) / 2,
                    time=candle["time"],
                ))
                used_indices.add(i)

        # Bearish OB: bullish candle (close > open) before strong bearish move.
        # ICT zone = candle BODY only.
        if is_bullish and i not in used_indices:
            next_slice = df.iloc[i + 1 : i + 5]
            displacement = candle["low"] - next_slice["low"].min()
            if displacement >= body:
                obs.append(OrderBlock(
                    type="BEARISH",
                    top=candle["close"],   # body top for a bullish candle
                    bottom=candle["open"], # body bottom for a bullish candle
                    mid=(candle["close"] + candle["open"]) / 2,
                    time=candle["time"],
                ))
                used_indices.add(i)

    return obs
