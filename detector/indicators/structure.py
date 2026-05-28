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


def find_swings(df: pd.DataFrame, lookback: int = 5) -> list[Swing]:
    """Pivot-based swing high/low detection."""
    swings: list[Swing] = []
    n = len(df)

    for i in range(lookback, n - lookback):
        highs = df["high"].values
        lows = df["low"].values

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


def determine_bias(swings: list[Swing]) -> Literal["BULLISH", "BEARISH", "NEUTRAL"]:
    """
    Determine market bias from the last 4+ swings.
    HH + HL pattern = BULLISH
    LH + LL pattern = BEARISH
    """
    highs = [s for s in swings if s.type == "HIGH"][-3:]
    lows = [s for s in swings if s.type == "LOW"][-3:]

    if len(highs) < 2 or len(lows) < 2:
        return "NEUTRAL"

    hh = highs[-1].price > highs[-2].price  # higher high
    hl = lows[-1].price > lows[-2].price    # higher low
    lh = highs[-1].price < highs[-2].price  # lower high
    ll = lows[-1].price < lows[-2].price    # lower low

    if hh and hl:
        return "BULLISH"
    if lh and ll:
        return "BEARISH"
    return "NEUTRAL"


def detect_structure_breaks(
    df: pd.DataFrame,
    swings: list[Swing],
    current_bias: Literal["BULLISH", "BEARISH", "NEUTRAL"],
) -> list[StructureBreak]:
    """
    BOS  = structure break in the direction of the prevailing trend.
    CHoCH = structure break AGAINST the prevailing trend (trend reversal signal).
    """
    breaks: list[StructureBreak] = []
    if len(df) < 2 or not swings:
        return breaks

    last_close = df.iloc[-1]["close"]
    prev_close = df.iloc[-2]["close"]

    recent_highs = [s for s in swings if s.type == "HIGH"]
    recent_lows = [s for s in swings if s.type == "LOW"]

    if recent_highs:
        prev_sh = recent_highs[-1].price
        if prev_close <= prev_sh < last_close:  # close above swing high
            break_dir: Literal["BULLISH", "BEARISH"] = "BULLISH"
            btype: Literal["BOS", "CHoCH"] = (
                "BOS" if current_bias == "BULLISH" else "CHoCH"
            )
            breaks.append(StructureBreak(btype, break_dir, prev_sh, df.iloc[-1]["time"]))

    if recent_lows:
        prev_sl = recent_lows[-1].price
        if prev_close >= prev_sl > last_close:  # close below swing low
            break_dir = "BEARISH"
            btype = "BOS" if current_bias == "BEARISH" else "CHoCH"
            breaks.append(StructureBreak(btype, break_dir, prev_sl, df.iloc[-1]["time"]))

    return breaks


def get_recent_choch(
    df: pd.DataFrame,
    swings: list[Swing],
    bias: Literal["BULLISH", "BEARISH", "NEUTRAL"],
    lookback_candles: int = 20,
) -> StructureBreak | None:
    """Return the most recent CHoCH in the last N candles, if any."""
    recent_df = df.iloc[-lookback_candles:]
    breaks = detect_structure_breaks(recent_df, swings, bias)
    chochs = [b for b in breaks if b.type == "CHoCH"]
    return chochs[-1] if chochs else None
