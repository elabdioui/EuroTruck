"""Buy-Side / Sell-Side Liquidity detection and sweep identification."""
import pandas as pd
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from config import Config

from .structure import Swing, find_swings


@dataclass
class LiquidityLevel:
    type: Literal["BSL", "SSL"]   # Buy-Side (above highs) / Sell-Side (below lows)
    price: float
    time: datetime
    swept: bool = False
    sweep_time: datetime | None = None
    sweep_idx: int | None = None   # positional index in the df where the sweep was detected


def find_equal_highs_lows(
    df: pd.DataFrame,
    tolerance_pips: float = 0.50,
) -> list[LiquidityLevel]:
    """
    Equal highs = BSL (stops sitting above).
    Equal lows  = SSL (stops sitting below).
    """
    pip_unit = Config.PIP
    tol = tolerance_pips * pip_unit
    levels: list[LiquidityLevel] = []

    highs = df["high"].values
    lows = df["low"].values
    times = df["time"].values

    for i in range(len(df) - 1):
        for j in range(i + 1, min(i + 20, len(df))):
            if abs(highs[i] - highs[j]) <= tol:
                levels.append(LiquidityLevel("BSL", (highs[i] + highs[j]) / 2, times[i]))
                break
            if abs(lows[i] - lows[j]) <= tol:
                levels.append(LiquidityLevel("SSL", (lows[i] + lows[j]) / 2, times[i]))
                break

    return levels


def find_swing_liquidity(
    swings: list[Swing],
    equal_threshold_pips: float = 0.50,
) -> list[LiquidityLevel]:
    """Major swing highs = BSL, major swing lows = SSL.
    Merges levels within equal_threshold_pips to avoid duplicate sweeps."""
    pip_unit = Config.PIP
    tol = equal_threshold_pips * pip_unit
    levels: list[LiquidityLevel] = []

    for s in swings:
        ltype: Literal["BSL", "SSL"] = "BSL" if s.type == "HIGH" else "SSL"
        merged = False
        for existing in levels:
            if existing.type == ltype and abs(existing.price - s.price) <= tol:
                # Keep the more recent level
                if s.time > existing.time:
                    existing.price = s.price
                    existing.time = s.time
                merged = True
                break
        if not merged:
            levels.append(LiquidityLevel(ltype, s.price, s.time))

    return levels


def detect_sweeps(
    df: pd.DataFrame,
    levels: list[LiquidityLevel],
    lookback_candles: int = 5,
) -> list[LiquidityLevel]:
    """
    A sweep occurs when price wicks through a liquidity level then closes back.
    BSL sweep: wick above BSL price then close below it.
    SSL sweep: wick below SSL price then close above it.
    """
    if df.empty:
        return levels

    offset = max(0, len(df) - lookback_candles)
    recent = df.iloc[offset:]

    for level in levels:
        if level.swept:
            continue
        for i, (_, row) in enumerate(recent.iterrows()):
            if level.type == "BSL":
                # wick above then close below
                if row["high"] > level.price and row["close"] < level.price:
                    level.swept = True
                    level.sweep_time = row["time"]
                    level.sweep_idx = offset + i
                    break
            elif level.type == "SSL":
                # wick below then close above
                if row["low"] < level.price and row["close"] > level.price:
                    level.swept = True
                    level.sweep_time = row["time"]
                    level.sweep_idx = offset + i
                    break

    return levels


def get_recent_sweep(
    levels: list[LiquidityLevel],
    sweep_type: Literal["BSL", "SSL"],
    lookback_candles: int = 10,
    df: pd.DataFrame | None = None,
) -> LiquidityLevel | None:
    """Return the most recently swept level of the given type."""
    swept = [l for l in levels if l.swept and l.type == sweep_type]
    if not swept:
        return None
    return max(swept, key=lambda l: l.sweep_time or l.time)


def _get_pdh_pdl(df: pd.DataFrame) -> tuple[float | None, float | None]:
    """Return (previous_day_high, previous_day_low) from an intraday dataframe."""
    if df.empty or "time" not in df.columns:
        return None, None
    dates = pd.to_datetime(df["time"]).dt.date
    today = dates.iloc[-1]
    prev = df[dates < today]
    if prev.empty:
        return None, None
    last_date = pd.to_datetime(prev["time"]).dt.date.iloc[-1]
    day_data = prev[pd.to_datetime(prev["time"]).dt.date == last_date]
    return float(day_data["high"].max()), float(day_data["low"].min())


def find_liquidity_target(
    df: pd.DataFrame,
    direction: str,
    current_price: float,
    tolerance_pips: float = 0.50,
    swing_lookback: int = 5,
) -> float | None:
    """
    Return the nearest untapped liquidity pool beyond price in the trade direction.

    Priority:
      1. Equal highs (LONG) / equal lows (SHORT) cluster beyond price.
      2. Previous Day High (LONG) / Previous Day Low (SHORT) beyond price.
      3. Nearest untapped swing High (LONG) / Low (SHORT) beyond price.

    Returns None when no pool is found.
    """
    liq_type: Literal["BSL", "SSL"] = "BSL" if direction == "LONG" else "SSL"

    # 1 — Equal highs/lows clusters
    eq_levels = find_equal_highs_lows(df, tolerance_pips=tolerance_pips)
    if direction == "LONG":
        above = [lvl.price for lvl in eq_levels if lvl.type == liq_type and lvl.price > current_price]
    else:
        above = [lvl.price for lvl in eq_levels if lvl.type == liq_type and lvl.price < current_price]
    if above:
        return min(above, key=lambda p: abs(p - current_price))

    # 2 — PDH / PDL
    pdh, pdl = _get_pdh_pdl(df)
    if direction == "LONG" and pdh is not None and pdh > current_price:
        return pdh
    if direction == "SHORT" and pdl is not None and pdl < current_price:
        return pdl

    # 3 — Nearest untapped swing
    swings = find_swings(df, lookback=swing_lookback)
    if direction == "LONG":
        candidates = [s.price for s in swings if s.type == "HIGH" and s.price > current_price]
        return min(candidates, key=lambda p: abs(p - current_price)) if candidates else None
    else:
        candidates = [s.price for s in swings if s.type == "LOW" and s.price < current_price]
        return max(candidates, key=lambda p: abs(p - current_price)) if candidates else None


def find_liquidity_pools(
    df: pd.DataFrame,
    swing_lookback: int = 5,
    tolerance_pips: float = 0.50,
) -> list[LiquidityLevel]:
    """
    Aggregate all liquidity pool types into one list.
    Sources: equal highs/lows clusters → PDH/PDL → major swing highs/lows.
    """
    pools: list[LiquidityLevel] = []
    pools.extend(find_equal_highs_lows(df, tolerance_pips=tolerance_pips))

    pdh, pdl = _get_pdh_pdl(df)
    if not df.empty:
        ref_time = df.iloc[0]["time"]
        if pdh is not None:
            pools.append(LiquidityLevel("BSL", pdh, ref_time))
        if pdl is not None:
            pools.append(LiquidityLevel("SSL", pdl, ref_time))

    swings = find_swings(df, lookback=swing_lookback)
    pools.extend(find_swing_liquidity(swings, equal_threshold_pips=tolerance_pips))
    return pools


def detect_sweep(
    df: pd.DataFrame,
    pool: LiquidityLevel,
    lookback_candles: int = 10,
) -> LiquidityLevel:
    """Check whether a single pool was swept in the most recent lookback_candles.

    Returns the pool with swept/sweep_time/sweep_idx updated in-place.
    """
    updated = detect_sweeps(df, [pool], lookback_candles=lookback_candles)
    return updated[0]


def detect_regime(
    df: pd.DataFrame,
    atr_period: int = 14,
    vol_multiplier: float = 2.0,
    range_multiplier: float = 0.5,
) -> Literal["trend", "range", "high_vol"]:
    """
    Classify market regime using ATR relative to its rolling mean.

    high_vol : current ATR > vol_multiplier  × mean ATR  → skip (news / erratic)
    range    : current ATR < range_multiplier × mean ATR  → skip (no momentum)
    trend    : otherwise                                  → allow setups
    """
    if len(df) < atr_period + 2:
        return "trend"   # insufficient data — default to allow

    high = df["high"].values
    low = df["low"].values
    close = df["close"].values

    tr = [
        max(high[i] - low[i], abs(high[i] - close[i - 1]), abs(low[i] - close[i - 1]))
        for i in range(1, len(df))
    ]
    tr_series = pd.Series(tr)
    atr = tr_series.rolling(atr_period).mean().dropna()

    if atr.empty:
        return "trend"

    current_atr = float(atr.iloc[-1])
    mean_atr = float(atr.mean())

    if mean_atr == 0:
        return "trend"

    if current_atr > vol_multiplier * mean_atr:
        return "high_vol"
    if current_atr < range_multiplier * mean_atr:
        return "range"
    return "trend"
