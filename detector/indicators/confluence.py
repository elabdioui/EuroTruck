"""Shared ICT entry-zone confluence helpers."""

import pandas as pd

from config import cfg
from .fvg import detect_fvg
from .order_block import detect_order_blocks


def has_fvg_or_ob_in_zone(
    m5: pd.DataFrame,
    zone_low: float,
    zone_high: float,
    direction: str,
) -> bool:
    """Return whether a closed M5 FVG or OB overlaps the directional zone."""
    if len(m5) < 5 or not {"open", "high", "low", "close"}.issubset(m5.columns):
        return False
    closed = m5.iloc[:-1].copy()
    if "time" not in closed.columns:
        if isinstance(closed.index, pd.DatetimeIndex):
            closed["time"] = pd.to_datetime(closed.index, utc=True, errors="coerce")
        else:
            closed["time"] = pd.date_range(
                "1970-01-01", periods=len(closed), freq="5min", tz="UTC"
            )
    expected = "BULLISH" if direction == "long" else "BEARISH"
    low, high = sorted((float(zone_low), float(zone_high)))

    fvgs = detect_fvg(closed, min_size_pips=cfg.FVG_MIN_SIZE_PIPS)
    for item in fvgs:
        item_low, item_high = sorted((float(item.bottom), float(item.top)))
        if item.type == expected and item_low <= high and item_high >= low:
            return True

    obs = detect_order_blocks(closed, lookback=cfg.OB_LOOKBACK)
    for item in obs:
        item_low, item_high = sorted((float(item.bottom), float(item.top)))
        if item.type == expected and item_low <= high and item_high >= low:
            return True
    return False
