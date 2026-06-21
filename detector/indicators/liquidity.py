"""Minimal buy-side/sell-side liquidity detection on closed candles."""

from dataclasses import dataclass

import pandas as pd

from config import cfg
from .structure import find_swings


@dataclass(frozen=True)
class LiquidityLevel:
    type: str  # "BSL" | "SSL"
    price: float
    candle_idx: int
    source: str  # "equal" | "swing"


def _market_frame(frame: pd.DataFrame) -> pd.DataFrame | None:
    if not {"high", "low", "close"}.issubset(frame.columns) or len(frame) < 3:
        return None
    closed = frame.iloc[:-1].copy()
    if "time" not in closed.columns:
        if isinstance(closed.index, pd.DatetimeIndex):
            closed["time"] = pd.to_datetime(closed.index, utc=True, errors="coerce")
        else:
            closed["time"] = pd.date_range(
                "1970-01-01", periods=len(closed), freq="5min", tz="UTC"
            )
    return closed


def _equal_levels(closed: pd.DataFrame, tolerance: float) -> list[LiquidityLevel]:
    levels: list[LiquidityLevel] = []
    highs = pd.to_numeric(closed["high"], errors="coerce").to_numpy()
    lows = pd.to_numeric(closed["low"], errors="coerce").to_numpy()
    for index in range(1, len(closed)):
        matching_highs = [
            prior for prior in range(index)
            if abs(float(highs[index]) - float(highs[prior])) <= tolerance
        ]
        matching_lows = [
            prior for prior in range(index)
            if abs(float(lows[index]) - float(lows[prior])) <= tolerance
        ]
        if matching_highs:
            prior = matching_highs[-1]
            levels.append(LiquidityLevel(
                "BSL", (float(highs[index]) + float(highs[prior])) / 2, index, "equal"
            ))
        if matching_lows:
            prior = matching_lows[-1]
            levels.append(LiquidityLevel(
                "SSL", (float(lows[index]) + float(lows[prior])) / 2, index, "equal"
            ))
    return levels


def find_equal_highs_lows(frame: pd.DataFrame) -> list[LiquidityLevel]:
    """Find adjacent equal highs/lows, excluding the forming candle."""
    closed = _market_frame(frame)
    if closed is None:
        return []
    tolerance = float(cfg.LIQUIDITY_EQUAL_TOLERANCE_PIPS) * float(cfg.PIP)
    return _equal_levels(closed, tolerance)


def find_swing_liquidity(frame: pd.DataFrame) -> list[LiquidityLevel]:
    """Convert confirmed swing highs/lows into BSL/SSL levels."""
    closed = _market_frame(frame)
    if closed is None:
        return []
    return [
        LiquidityLevel(
            "BSL" if swing.type == "HIGH" else "SSL",
            float(swing.price),
            int(swing.index),
            "swing",
        )
        for swing in find_swings(closed, lookback=cfg.SWING_LOOKBACK)
    ]


def find_recent_liquidity_sweep(
    frame: pd.DataFrame, direction: str
) -> LiquidityLevel | None:
    """Return the latest rejection sweep coherent with the trade direction."""
    if direction not in {"long", "short"}:
        return None
    closed = _market_frame(frame)
    if closed is None:
        return None
    tolerance = float(cfg.LIQUIDITY_EQUAL_TOLERANCE_PIPS) * float(cfg.PIP)
    levels = _equal_levels(closed, tolerance)
    levels.extend(
        LiquidityLevel(
            "BSL" if swing.type == "HIGH" else "SSL",
            float(swing.price),
            int(swing.index),
            "swing",
        )
        for swing in find_swings(closed, lookback=cfg.SWING_LOOKBACK)
    )
    expected = "SSL" if direction == "long" else "BSL"
    start = max(0, len(closed) - int(cfg.LIQUIDITY_SWEEP_LOOKBACK_M5))
    candidates: list[tuple[int, LiquidityLevel]] = []
    for level in levels:
        if level.type != expected:
            continue
        for index in range(max(start, level.candle_idx + 1), len(closed)):
            bar = closed.iloc[index]
            if direction == "long":
                swept = float(bar["low"]) < level.price <= float(bar["close"])
            else:
                swept = float(bar["high"]) > level.price >= float(bar["close"])
            if swept:
                candidates.append((index, level))
    return max(candidates, key=lambda item: item[0])[1] if candidates else None
