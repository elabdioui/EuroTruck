"""Fair Value Gap (Imbalance) detection."""
import pandas as pd
from dataclasses import dataclass, field
from datetime import datetime

from config import Config


@dataclass
class FVG:
    type: str           # "BULLISH" | "BEARISH"
    top: float
    bottom: float
    mid: float
    size: float
    time: datetime
    candle_idx: int = 0  # positional index of the middle candle within the passed df
    filled: bool = False
    partially_filled: bool = False

    @property
    def label(self) -> str:
        return f"FVG_{self.type[0]}"


def detect_fvg(df: pd.DataFrame, min_size_pips: float = 3.0) -> list[FVG]:
    """
    3-candle pattern: gap between candle[i-1] and candle[i+1].
    Pip size is resolved from the configured live symbol at startup.
    """
    if len(df) < 4:
        return []

    pip_unit = Config.PIP
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
                    candle_idx=i,
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
                    candle_idx=i,
                ))

    return fvgs
