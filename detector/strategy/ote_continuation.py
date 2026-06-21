import logging

import pandas as pd

import stats
from config import cfg
from indicators.bias import ema
from indicators.fibonacci import (
    compute_fib_from_sweep,
    compute_fib_from_sweep_bearish,
)
from indicators.structure import find_swings, get_recent_structure_break
from ._bars import closed
from .ict_tags import build_ict_tags
from .registry import SetupSpec, register


NAME = "ote_continuation"
PATTERN = "h4_bias_ote_pullback"

log = logging.getLogger(__name__)


def _reject(reason: str) -> None:
    log.debug("ote_continuation reject: %s", reason)
    stats.record(NAME, reason)
    return None


def _has_market_columns(frame: pd.DataFrame) -> bool:
    return {"high", "low", "close"}.issubset(frame.columns)


def _with_time_column(frame: pd.DataFrame) -> pd.DataFrame | None:
    if "time" in frame.columns:
        times = pd.to_datetime(frame["time"], utc=True, errors="coerce")
    elif isinstance(frame.index, pd.DatetimeIndex):
        times = pd.to_datetime(frame.index, utc=True, errors="coerce")
    else:
        return None
    if pd.isna(times).any():
        return None
    result = frame.copy()
    result["time"] = times
    return result


def _find_impulse(frame: pd.DataFrame, direction: str) -> tuple[float, float]:
    """Find the largest bias-aligned, chronologically valid move in the window."""
    highs = pd.to_numeric(frame["high"], errors="coerce").to_numpy()
    lows = pd.to_numeric(frame["low"], errors="coerce").to_numpy()
    best_low = best_high = float("nan")
    best_move = -1.0

    if direction == "long":
        running_low = float(lows[0])
        for position in range(1, len(frame)):
            move = float(highs[position]) - running_low
            if move >= best_move:
                best_low, best_high, best_move = running_low, float(highs[position]), move
            running_low = min(running_low, float(lows[position]))
    else:
        running_high = float(highs[0])
        for position in range(1, len(frame)):
            move = running_high - float(lows[position])
            if move >= best_move:
                best_low, best_high, best_move = float(lows[position]), running_high, move
            running_high = max(running_high, float(highs[position]))

    return best_low, best_high


def scan(tf_data: dict) -> dict | None:
    m15 = tf_data.get("M15")
    m5 = tf_data.get("M5")
    h4 = tf_data.get("H4")
    if (
        not isinstance(m15, pd.DataFrame)
        or not isinstance(m5, pd.DataFrame)
        or not isinstance(h4, pd.DataFrame)
        or len(m15) < 96
        or len(m5) < 100
        or len(h4) < max(30, cfg.OTE_CONT_BIAS_EMA)
        or not _has_market_columns(m15)
        or not _has_market_columns(m5)
        or not _has_market_columns(h4)
    ):
        return _reject("insufficient data")

    m15c = closed(m15)
    m5c = closed(m5)
    h4c = closed(h4)

    pip = float(cfg.PIP)
    if pip <= 0:
        return _reject("invalid pip size")

    h4_ema = ema(h4c["close"], cfg.OTE_CONT_BIAS_EMA).iloc[-1]
    h4_close = pd.to_numeric(h4c["close"], errors="coerce").iloc[-1]
    if pd.isna(h4_ema) or pd.isna(h4_close) or h4_ema == 0:
        return _reject("insufficient data")
    if abs(h4_close - h4_ema) / abs(h4_ema) < 0.001:
        return _reject("h4 bias unclear")
    direction = "long" if h4_close > h4_ema else "short"

    impulse = m15c.iloc[-24:]
    if impulse[["high", "low"]].apply(pd.to_numeric, errors="coerce").isna().any().any():
        return _reject("insufficient data")
    impulse_low, impulse_high = _find_impulse(impulse, direction)
    if (impulse_high - impulse_low) / pip < cfg.OTE_CONT_MIN_IMPULSE_PIPS:
        return _reject("impulse too small")

    if direction == "long":
        fib = compute_fib_from_sweep(
            impulse_low, impulse_high, cfg.OTE_LOW, cfg.OTE_HIGH
        )
        anchor = impulse_low
    else:
        fib = compute_fib_from_sweep_bearish(
            impulse_high, impulse_low, cfg.OTE_LOW, cfg.OTE_HIGH
        )
        anchor = impulse_high

    entry = float(pd.to_numeric(m5c["close"], errors="coerce").iloc[-1])
    tolerance = cfg.OTE_ENTRY_TOLERANCE_PIPS * pip
    ote_low = min(fib.ote_low, fib.ote_high) - tolerance
    ote_high = max(fib.ote_low, fib.ote_high) + tolerance
    if pd.isna(entry) or not ote_low <= entry <= ote_high:
        return _reject("outside OTE")

    structure_m5 = _with_time_column(m5c)
    if structure_m5 is None:
        return _reject("insufficient data")
    swings = find_swings(structure_m5, lookback=cfg.SWING_LOOKBACK)
    bos_direction = "BULLISH" if direction == "long" else "BEARISH"
    bos = get_recent_structure_break(
        structure_m5, swings, bos_direction, lookback_candles=15
    )
    recent_start = max(0, len(m5c) - 15)
    recent_closes = pd.to_numeric(m5c["close"], errors="coerce").iloc[recent_start:]
    pullback_indices = [
        recent_start + offset
        for offset, price in enumerate(recent_closes)
        if ote_low <= price <= ote_high
    ]
    if bos is None or not pullback_indices or bos.candle_idx < pullback_indices[0]:
        return _reject("no continuation BOS")

    if direction == "long":
        sl = anchor - cfg.SL_BUFFER_PIPS * pip
        risk = entry - sl
        tp1 = entry + risk
        tp_final = entry + 2.0 * risk
    else:
        sl = anchor + cfg.SL_BUFFER_PIPS * pip
        risk = sl - entry
        tp1 = entry - risk
        tp_final = entry - 2.0 * risk
    if risk <= 0 or risk / pip < cfg.OTE_CONT_MIN_RISK_PIPS:
        return _reject("risk too tight")

    tags = build_ict_tags(
        tf_data, direction, ote_low, ote_high, bias_period=cfg.OTE_CONT_BIAS_EMA
    )
    tags["h_bias_aligned"] = True
    if cfg.OTE_CONT_REQUIRE_FVG_OB and not tags["fvg_ob_confluence"]:
        return _reject("no FVG/OB confluence in OTE zone")

    signal = {
        "direction": direction,
        "pattern": PATTERN,
        "entry": float(entry),
        "sl": float(sl),
        "tp1": float(tp1),
        "tp_final": float(tp_final),
        "meta": {
            "h4_ema": float(h4_ema),
            "impulse_low": float(impulse_low),
            "impulse_high": float(impulse_high),
            **tags,
        },
    }
    stats.record(NAME, "EMIT")
    log.info(
        "ote_continuation candidate %s entry=%s sl=%s tp1=%s tp_final=%s",
        direction, entry, sl, tp1, tp_final,
    )
    return signal


register(SetupSpec(
    name=NAME,
    scan=scan,
    killzone_mode="preferred",
    killzones=("LONDON", "NY_AM"),
    cooldown_seconds=2400,
))
