import logging

import pandas as pd

import stats
from config import cfg
from indicators.fibonacci import (
    compute_fib_from_sweep,
    compute_fib_from_sweep_bearish,
)
from indicators.structure import find_swings, get_recent_structure_break
from .registry import SetupSpec, register


NAME = "london_judas"
PATTERN = "asia_sweep_bos_ote"

log = logging.getLogger(__name__)


def _reject(reason: str) -> None:
    log.debug("london_judas reject: %s", reason)
    stats.record(NAME, reason)
    return None


def _timestamps(frame: pd.DataFrame) -> pd.DatetimeIndex | None:
    if "time" in frame.columns:
        return pd.DatetimeIndex(pd.to_datetime(frame["time"], utc=True, errors="coerce"))
    if isinstance(frame.index, pd.DatetimeIndex):
        return pd.DatetimeIndex(pd.to_datetime(frame.index, utc=True, errors="coerce"))
    return None


def _has_market_columns(frame: pd.DataFrame) -> bool:
    return {"high", "low", "close"}.issubset(frame.columns)


def _find_sweep(recent: pd.DataFrame, asia_low: float, asia_high: float) -> str | None:
    last_close = float(recent.iloc[-1]["close"])
    long_hit = float(recent["low"].min()) < asia_low and last_close > asia_low
    short_hit = float(recent["high"].max()) > asia_high and last_close < asia_high

    if long_hit and short_hit:
        long_position = int(recent["low"].to_numpy().argmin())
        short_position = int(recent["high"].to_numpy().argmax())
        return "long" if long_position > short_position else "short"
    if long_hit:
        return "long"
    if short_hit:
        return "short"
    return None


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
        or len(h4) < 30
        or not _has_market_columns(m15)
        or not _has_market_columns(m5)
    ):
        return _reject("insufficient data")

    m15_times = _timestamps(m15)
    m5_times = _timestamps(m5)
    if m15_times is None or m5_times is None or pd.isna(m5_times[-1]):
        return _reject("missing UTC timestamps")

    session_date = m5_times[-1].date()
    session_start = pd.Timestamp(
        year=session_date.year,
        month=session_date.month,
        day=session_date.day,
        hour=cfg.ASIA_SESSION_START_UTC,
        tz="UTC",
    )
    session_end = pd.Timestamp(
        year=session_date.year,
        month=session_date.month,
        day=session_date.day,
        hour=cfg.ASIA_SESSION_END_UTC,
        tz="UTC",
    )
    asia = m15.loc[(m15_times >= session_start) & (m15_times < session_end)]
    if asia.empty:
        return _reject("asia session unavailable")

    pip = float(cfg.PIP)
    if pip <= 0:
        return _reject("invalid pip size")

    asia_high = float(asia["high"].max())
    asia_low = float(asia["low"].min())
    asia_range_pips = (asia_high - asia_low) / pip
    if asia_range_pips < cfg.LONDON_JUDAS_MIN_RANGE_PIPS:
        return _reject("asia range too tight")

    recent = m5.iloc[-cfg.LONDON_JUDAS_LOOKBACK_M5:]
    direction = _find_sweep(recent, asia_low, asia_high)
    if direction is None:
        return _reject("no asia range sweep rejection")

    structure_m5 = m5
    if "time" not in structure_m5.columns:
        structure_m5 = m5.copy()
        structure_m5["time"] = m5_times
    swings = find_swings(structure_m5, lookback=cfg.SWING_LOOKBACK)
    bos_direction = "BULLISH" if direction == "long" else "BEARISH"
    bos = get_recent_structure_break(
        structure_m5, swings, bos_direction, lookback_candles=20
    )
    if bos is None:
        return _reject(f"no {direction} M5 structure break")

    anchor_type = "LOW" if direction == "long" else "HIGH"
    anchors = [
        swing for swing in swings
        if swing.type == anchor_type and swing.index < bos.candle_idx
    ]
    if not anchors:
        return _reject(f"no confirmed {direction} BOS anchor")
    anchor = anchors[-1]

    displacement = m5.iloc[anchor.index:]
    if direction == "long":
        displacement_extreme = float(displacement["high"].max())
        if displacement_extreme <= float(anchor.price):
            return _reject("invalid bullish displacement")
        fib = compute_fib_from_sweep(
            float(anchor.price), displacement_extreme, cfg.OTE_LOW, cfg.OTE_HIGH
        )
    else:
        displacement_extreme = float(displacement["low"].min())
        if displacement_extreme >= float(anchor.price):
            return _reject("invalid bearish displacement")
        fib = compute_fib_from_sweep_bearish(
            float(anchor.price), displacement_extreme, cfg.OTE_LOW, cfg.OTE_HIGH
        )

    entry = float(m5.iloc[-1]["close"])
    tolerance = cfg.OTE_ENTRY_TOLERANCE_PIPS * pip
    ote_low = min(fib.ote_low, fib.ote_high) - tolerance
    ote_high = max(fib.ote_low, fib.ote_high) + tolerance
    if not ote_low <= entry <= ote_high:
        return _reject("current price outside OTE zone")

    if direction == "long":
        sl = float(anchor.price) - cfg.SL_BUFFER_PIPS * pip
        risk = entry - sl
        tp1 = entry + risk
        tp_final = entry + 2.0 * risk
    else:
        sl = float(anchor.price) + cfg.SL_BUFFER_PIPS * pip
        risk = sl - entry
        tp1 = entry - risk
        tp_final = entry - 2.0 * risk

    if risk <= 0 or risk / pip < cfg.LONDON_JUDAS_MIN_RISK_PIPS:
        return _reject("risk below minimum")

    signal = {
        "direction": direction,
        "pattern": PATTERN,
        "entry": float(entry),
        "sl": float(sl),
        "tp1": float(tp1),
        "tp_final": float(tp_final),
        "meta": {
            "asia_high": asia_high,
            "asia_low": asia_low,
            "bos_anchor": float(anchor.price),
        },
    }
    stats.record(NAME, "EMIT")
    log.info(
        "london_judas candidate %s entry=%s sl=%s tp1=%s tp_final=%s",
        direction, entry, sl, tp1, tp_final,
    )
    return signal


register(SetupSpec(
    name=NAME,
    scan=scan,
    killzone_mode="required",
    killzones=("LONDON",),
    cooldown_seconds=3600,
))
