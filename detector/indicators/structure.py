"""Market structure: swing highs/lows, BOS, CHoCH, bias."""
import pandas as pd
import numpy as np
from dataclasses import dataclass
from datetime import datetime
from typing import Literal


@dataclass
class Swing:
    type: Literal["HIGH", "LOW"]
    price: float
    time: datetime
    index: int


@dataclass
class StructureBreak:
    type: Literal["BOS", "CHoCH"]
    direction: Literal["BULLISH", "BEARISH"]  # direction of the break
    broken_level: float
    time: datetime
    candle_idx: int = 0  # positional index of the breaking candle within the passed df


def find_swings(df: pd.DataFrame, lookback: int = 5) -> list[Swing]:
    """Pivot-based swing high/low detection."""
    swings: list[Swing] = []
    n = len(df)
    # Extract arrays once — avoids re-allocating on every iteration
    highs = df["high"].values
    lows = df["low"].values

    for i in range(lookback, n - lookback):
        is_sh = all(highs[i] > highs[i - j] for j in range(1, lookback + 1)) and \
                all(highs[i] > highs[i + j] for j in range(1, lookback + 1))
        is_sl = all(lows[i] < lows[i - j] for j in range(1, lookback + 1)) and \
                all(lows[i] < lows[i + j] for j in range(1, lookback + 1))

        if is_sh:
            swings.append(Swing("HIGH", highs[i], df.iloc[i]["time"], i))
        if is_sl:
            swings.append(Swing("LOW", lows[i], df.iloc[i]["time"], i))

    swings.sort(key=lambda s: s.index)
    return swings


def detect_structure_breaks(
    df: pd.DataFrame,
    swings: list[Swing],
    current_bias: Literal["BULLISH", "BEARISH", "NEUTRAL"],
) -> list[StructureBreak]:
    """
    BOS  = cassure de structure dans le sens du trend dominant.
    CHoCH = cassure de structure CONTRE le trend dominant.

    Pour chaque bougie, on compare son close au dernier swing High/Low
    ANTÉRIEUR à cette bougie (référence mobile), et non à un niveau figé.
    Après une cassure, le niveau de référence avance pour éviter de
    réenregistrer la même cassure plusieurs fois.
    """
    breaks: list[StructureBreak] = []
    if len(df) < 2 or not swings:
        return breaks

    highs = [s for s in swings if s.type == "HIGH"]
    lows = [s for s in swings if s.type == "LOW"]
    if not highs and not lows:
        return breaks

    hi_idx = 0   # pointeur sur le prochain swing High candidat
    lo_idx = 0
    active_sh: float | None = None   # dernier swing High antérieur à la bougie i
    active_sl: float | None = None

    for i in range(1, len(df)):
        prev_close = df.iloc[i - 1]["close"]
        curr_close = df.iloc[i]["close"]
        candle_time = df.iloc[i]["time"]

        # Avancer les références : tout swing dont l'index < i devient "actif"
        while hi_idx < len(highs) and highs[hi_idx].index < i:
            active_sh = highs[hi_idx].price
            hi_idx += 1
        while lo_idx < len(lows) and lows[lo_idx].index < i:
            active_sl = lows[lo_idx].price
            lo_idx += 1

        # Cassure haussière du dernier swing High antérieur
        if active_sh is not None and prev_close <= active_sh < curr_close:
            btype: Literal["BOS", "CHoCH"] = "BOS" if current_bias == "BULLISH" else "CHoCH"
            breaks.append(StructureBreak(btype, "BULLISH", active_sh, candle_time, candle_idx=i))
            active_sh = None   # consommé — attend le prochain swing High pour rearmer

        # Cassure baissière du dernier swing Low antérieur
        if active_sl is not None and prev_close >= active_sl > curr_close:
            btype = "BOS" if current_bias == "BEARISH" else "CHoCH"
            breaks.append(StructureBreak(btype, "BEARISH", active_sl, candle_time, candle_idx=i))
            active_sl = None

    return breaks

def get_recent_structure_break(
    df: pd.DataFrame,
    swings: list[Swing],
    direction: Literal["BULLISH", "BEARISH"],
    lookback_candles: int = 15,
) -> StructureBreak | None:
    """
    Most recent structure break (BOS or CHoCH — label irrelevant) in the given
    direction, occurring within the last `lookback_candles` candles of `df`.

    IMPORTANT: detect_structure_breaks is called on the FULL df so that
    swing.index values (positional indices into the full df) stay aligned
    with the loop index. Recency is filtered afterwards via candle_idx.
    """
    breaks = detect_structure_breaks(df, swings, current_bias="NEUTRAL")
    cutoff = max(0, len(df) - lookback_candles)
    recent = [b for b in breaks if b.direction == direction and b.candle_idx >= cutoff]
    return recent[-1] if recent else None
