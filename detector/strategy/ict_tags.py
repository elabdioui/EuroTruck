"""Uniform metadata builders for measurable ICT confluences."""

import pandas as pd

from config import cfg
from indicators.bias import ema
from indicators.confluence import has_fvg_or_ob_in_zone
from indicators.liquidity import find_recent_liquidity_sweep


def htf_bias(tf_data: dict, period: int = 20) -> str:
    """Return H4 bias when available, otherwise H1 bias, using closed bars."""
    for timeframe in ("H4", "H1"):
        frame = tf_data.get(timeframe)
        if not isinstance(frame, pd.DataFrame) or "close" not in frame or len(frame) <= period:
            continue
        closed = frame.iloc[:-1]
        average = ema(closed["close"], period).iloc[-1]
        close = pd.to_numeric(closed["close"], errors="coerce").iloc[-1]
        if pd.isna(average) or pd.isna(close) or close == average:
            return "flat"
        return "long" if close > average else "short"
    return "flat"


def build_ict_tags(
    tf_data: dict,
    direction: str,
    zone_low: float,
    zone_high: float,
    *,
    bias_period: int = 20,
    forced_fvg_ob: bool | None = None,
    swept_level: float | None = None,
) -> dict:
    """Build the three uniform, non-gating ICT metadata tags."""
    m5 = tf_data.get("M5")
    confluence = bool(forced_fvg_ob)
    sweep = None
    if isinstance(m5, pd.DataFrame):
        if forced_fvg_ob is None:
            confluence = has_fvg_or_ob_in_zone(m5, zone_low, zone_high, direction)
        if swept_level is None:
            sweep = find_recent_liquidity_sweep(m5, direction)
    level = swept_level if swept_level is not None else (sweep.price if sweep else None)
    return {
        "h_bias_aligned": htf_bias(tf_data, bias_period) == direction,
        "fvg_ob_confluence": confluence,
        "liquidity_confluence": level is not None,
        "swept_level": float(level) if level is not None else None,
    }
