"""Fair Value Gap (Imbalance) detection."""
import pandas as pd
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class FVG:
    type: str           # "BULLISH" | "BEARISH"
    top: float
    bottom: float
    mid: float
    size: float
    time: datetime
    filled: bool = False
    partially_filled: bool = False

    @property
    def label(self) -> str:
        return f"FVG_{self.type[0]}"


def detect_fvg(df: pd.DataFrame, min_size_pips: float = 3.0) -> list[FVG]:
    """
    3-candle pattern: gap between candle[i-1] and candle[i+1].
    XAUUSD pip = 0.10 (1 point = 0.01, 1 pip = 0.10)
    """
    if len(df) < 4:
        return []

    pip_unit = 0.10
    min_size = min_size_pips * pip_unit
    fvgs: list[FVG] = []

    # Upper bound is len(df) - 2 so c3 = df.iloc[i+1] is always the last CLOSED
    # candle, never the still-forming current candle (df.iloc[-1]).
    for i in range(1, len(df) - 2):
        c1 = df.iloc[i - 1]
        c3 = df.iloc[i + 1]
        c2 = df.iloc[i]

        # Bullish FVG: gap between c1.high and c3.low (c2 is the impulse up)
        if c3["low"] > c1["high"]:
            gap = c3["low"] - c1["high"]
            if gap >= min_size:
                fvgs.append(FVG(
                    type="BULLISH",
                    top=c3["low"],
                    bottom=c1["high"],
                    mid=(c3["low"] + c1["high"]) / 2,
                    size=gap,
                    time=c2["time"],
                ))

        # Bearish FVG: gap between c1.low and c3.high (c2 is the impulse down)
        if c3["high"] < c1["low"]:
            gap = c1["low"] - c3["high"]
            if gap >= min_size:
                fvgs.append(FVG(
                    type="BEARISH",
                    top=c1["low"],
                    bottom=c3["high"],
                    mid=(c1["low"] + c3["high"]) / 2,
                    size=gap,
                    time=c2["time"],
                ))

    return fvgs


def filter_unfilled_fvg(fvgs: list[FVG], current_price: float) -> list[FVG]:
    """Mark FVGs that price has entered as filled."""
    result = []
    for fvg in fvgs:
        if fvg.type == "BULLISH" and current_price < fvg.bottom:
            # Strict <: price exactly AT the bottom is still a valid entry edge
            fvg.filled = True
        elif fvg.type == "BULLISH" and fvg.bottom <= current_price < fvg.top:
            fvg.partially_filled = True
        elif fvg.type == "BEARISH" and current_price > fvg.top:
            # Strict >: price exactly AT the top is still a valid entry edge
            fvg.filled = True
        elif fvg.type == "BEARISH" and fvg.bottom < current_price <= fvg.top:
            fvg.partially_filled = True
        result.append(fvg)
    return result


def get_recent_fvg(fvgs: list[FVG], direction: str, n: int = 3) -> list[FVG]:
    """Return the N most recent unfilled FVGs matching the direction."""
    matching = [f for f in fvgs if f.type == direction and not f.filled]
    return matching[-n:]
