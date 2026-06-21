import logging
from zoneinfo import ZoneInfo

import pandas as pd

import stats
from config import cfg
from indicators.fibonacci import (
    compute_fib_from_sweep,
    compute_fib_from_sweep_bearish,
)
from indicators.structure import find_swings, get_recent_structure_break
from ._bars import closed
from .ict_tags import build_ict_tags
from .registry import SetupSpec, register


NAME = "overlap_bos"
PATTERN = "ldn_ny_overlap_m15_bos_pullback"

log = logging.getLogger(__name__)
_NY_TZ = ZoneInfo("America/New_York")


def _reject(reason: str) -> None:
    log.debug("overlap_bos reject: %s", reason)
    stats.record(NAME, reason)
    return None


def _timestamps(frame: pd.DataFrame) -> pd.DatetimeIndex | None:
    if "time" in frame.columns:
        times = pd.to_datetime(frame["time"], utc=True, errors="coerce")
    elif isinstance(frame.index, pd.DatetimeIndex):
        times = pd.to_datetime(frame.index, utc=True, errors="coerce")
    else:
        return None
    index = pd.DatetimeIndex(times)
    return None if pd.isna(index).any() else index


def _ny_timestamp(value) -> pd.Timestamp:
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is None:
        timestamp = timestamp.tz_localize("UTC")
    return timestamp.tz_convert(_NY_TZ)


def scan(tf_data: dict) -> dict | None:
    m15 = tf_data.get("M15")
    m5 = tf_data.get("M5")
    if (
        not isinstance(m15, pd.DataFrame)
        or not isinstance(m5, pd.DataFrame)
        or len(m15) < 100
        or len(m5) < 100
        or not {"high", "low", "close"}.issubset(m15.columns)
        or "close" not in m5.columns
    ):
        return _reject("insufficient data")

    m15c = closed(m15)
    m5c = closed(m5)

    m15_times = _timestamps(m15c)
    m5_times = _timestamps(m5c)
    if m15_times is None or m5_times is None:
        return _reject("insufficient data")
    ny_now = m5_times[-1].tz_convert(_NY_TZ)
    if not (
        cfg.OVERLAP_BOS_NY_START_HOUR
        <= ny_now.hour
        < cfg.OVERLAP_BOS_NY_END_HOUR
    ):
        return _reject(f"outside overlap window (NY hour={ny_now.hour})")

    structure_m15 = m15c.copy()
    structure_m15["time"] = m15_times
    swings = find_swings(structure_m15, lookback=cfg.SWING_LOOKBACK)
    candidates = [
        get_recent_structure_break(
            structure_m15, swings, direction, lookback_candles=12
        )
        for direction in ("BULLISH", "BEARISH")
    ]
    window_start = ny_now.normalize() + pd.Timedelta(
        hours=cfg.OVERLAP_BOS_NY_START_HOUR
    )
    candidates = [
        bos for bos in candidates
        if bos is not None and window_start <= _ny_timestamp(bos.time) <= ny_now
    ]
    if not candidates:
        return _reject("no M15 BOS")
    bos = max(candidates, key=lambda candidate: candidate.candle_idx)
    direction = "long" if bos.direction == "BULLISH" else "short"

    anchor_type = "LOW" if direction == "long" else "HIGH"
    anchors = [
        swing for swing in swings
        if swing.type == anchor_type and swing.index < bos.candle_idx
    ]
    if not anchors:
        return _reject("no M15 BOS anchor")
    anchor = anchors[-1]

    displacement = m15c.iloc[bos.candle_idx:]
    if direction == "long":
        displacement_extreme = float(
            pd.to_numeric(displacement["high"], errors="coerce").max()
        )
        if pd.isna(displacement_extreme) or displacement_extreme <= anchor.price:
            return _reject("outside pullback zone")
        fib = compute_fib_from_sweep(
            float(anchor.price),
            displacement_extreme,
            cfg.OVERLAP_BOS_FIB_LOW,
            cfg.OVERLAP_BOS_FIB_HIGH,
        )
    else:
        displacement_extreme = float(
            pd.to_numeric(displacement["low"], errors="coerce").min()
        )
        if pd.isna(displacement_extreme) or displacement_extreme >= anchor.price:
            return _reject("outside pullback zone")
        fib = compute_fib_from_sweep_bearish(
            float(anchor.price),
            displacement_extreme,
            cfg.OVERLAP_BOS_FIB_LOW,
            cfg.OVERLAP_BOS_FIB_HIGH,
        )

    pip = float(cfg.PIP)
    if pip <= 0:
        return _reject("invalid pip size")
    entry = float(pd.to_numeric(m5c["close"], errors="coerce").iloc[-1])
    tolerance = cfg.OTE_ENTRY_TOLERANCE_PIPS * pip
    pullback_low = min(fib.ote_low, fib.ote_high) - tolerance
    pullback_high = max(fib.ote_low, fib.ote_high) + tolerance
    if pd.isna(entry) or not pullback_low <= entry <= pullback_high:
        return _reject("outside pullback zone")

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
    if risk <= 0 or risk / pip < cfg.OVERLAP_BOS_MIN_RISK_PIPS:
        return _reject("risk below minimum")

    tags = build_ict_tags(tf_data, direction, pullback_low, pullback_high)
    if cfg.OVERLAP_BOS_REQUIRE_BIAS and not tags["h_bias_aligned"]:
        return _reject("HTF bias not aligned")
    if cfg.OVERLAP_BOS_REQUIRE_FVG_OB and not tags["fvg_ob_confluence"]:
        return _reject("no FVG/OB confluence in pullback zone")

    signal = {
        "direction": direction,
        "pattern": PATTERN,
        "entry": float(entry),
        "sl": float(sl),
        "tp1": float(tp1),
        "tp_final": float(tp_final),
        "meta": {
            "m15_bos_anchor": float(anchor.price),
            "displacement_extreme": float(displacement_extreme),
            "ny_hour": int(ny_now.hour),
            **tags,
        },
    }
    stats.record(NAME, "EMIT")
    log.info(
        "overlap_bos candidate %s entry=%s sl=%s tp1=%s tp_final=%s",
        direction, entry, sl, tp1, tp_final,
    )
    return signal


register(SetupSpec(
    name=NAME,
    scan=scan,
    killzone_mode="required",
    killzones=("NY_AM",),
    cooldown_seconds=2400,
))
