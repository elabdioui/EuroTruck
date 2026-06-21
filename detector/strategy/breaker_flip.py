"""Detect failed M5 order blocks retesting as breaker support/resistance."""

import logging

import pandas as pd

import stats
from config import cfg
from indicators.bias import ema
from indicators.order_block import OrderBlock, detect_order_blocks
from .ict_tags import build_ict_tags
from .registry import SetupSpec, register


NAME = "breaker_flip"
PATTERN = "broken_ob_flip_retest"

log = logging.getLogger(__name__)


def _reject(reason: str) -> None:
    log.debug("breaker_flip reject: %s", reason)
    stats.record(NAME, reason)
    return None


def _timestamps(frame: pd.DataFrame) -> pd.DatetimeIndex | None:
    if "time" in frame.columns:
        values = pd.to_datetime(frame["time"], utc=True, errors="coerce")
    elif isinstance(frame.index, pd.DatetimeIndex):
        values = pd.to_datetime(frame.index, utc=True, errors="coerce")
    else:
        return None
    timestamps = pd.DatetimeIndex(values)
    return None if pd.isna(timestamps).any() else timestamps


def _formation_index(ob: OrderBlock, timestamps: pd.DatetimeIndex) -> int | None:
    formed_at = pd.Timestamp(ob.time)
    if formed_at.tzinfo is None:
        formed_at = formed_at.tz_localize("UTC")
    else:
        formed_at = formed_at.tz_convert("UTC")
    matches = timestamps == formed_at
    positions = matches.nonzero()[0]
    return int(positions[-1]) if len(positions) else None


def _h1_direction(h1: pd.DataFrame) -> str:
    average = ema(h1["close"], 20).iloc[-1]
    close = pd.to_numeric(h1["close"], errors="coerce").iloc[-1]
    if pd.isna(average) or pd.isna(close) or close == average:
        return "flat"
    return "long" if close > average else "short"


def _broken_candidate(
    ob: OrderBlock,
    formation_index: int,
    m5: pd.DataFrame,
) -> tuple[str, int] | None:
    # The last candle is the retest candle, so breakage must precede it.
    after_formation = m5.iloc[formation_index + 1 : -1]
    if after_formation.empty:
        return None
    if ob.type == "BULLISH":
        broken = pd.to_numeric(after_formation["close"], errors="coerce") < float(ob.bottom)
        direction = "short"
    elif ob.type == "BEARISH":
        broken = pd.to_numeric(after_formation["close"], errors="coerce") > float(ob.top)
        direction = "long"
    else:
        return None
    positions = broken.to_numpy().nonzero()[0]
    if not len(positions):
        return None
    return direction, formation_index + 1 + int(positions[0])


def scan(tf_data: dict) -> dict | None:
    m5 = tf_data.get("M5")
    h1 = tf_data.get("H1")
    required_m5 = {"open", "high", "low", "close"}
    if (
        not isinstance(m5, pd.DataFrame)
        or not isinstance(h1, pd.DataFrame)
        or len(m5) < 100
        or len(h1) < 30
        or not required_m5.issubset(m5.columns)
        or "close" not in h1.columns
    ):
        return _reject("insufficient data")

    timestamps = _timestamps(m5)
    if timestamps is None:
        return _reject("insufficient data")
    pip = float(cfg.PIP)
    if pip <= 0:
        return _reject("invalid pip size")

    structure_m5 = m5.copy()
    structure_m5["time"] = timestamps
    obs = detect_order_blocks(structure_m5, lookback=cfg.OB_LOOKBACK)
    oldest_allowed = len(m5) - int(cfg.BREAKER_LOOKBACK_M5)
    recent_obs: list[tuple[int, OrderBlock]] = []
    for ob in obs:
        formation_index = _formation_index(ob, timestamps)
        if formation_index is not None and formation_index >= oldest_allowed:
            recent_obs.append((formation_index, ob))
    if not recent_obs:
        return _reject("no OB in lookback")

    entry = float(pd.to_numeric(m5["close"], errors="coerce").iloc[-1])
    tolerance = float(cfg.BREAKER_RETEST_TOLERANCE_PIPS) * pip
    candidates: list[tuple[int, int, OrderBlock, str]] = []
    for formation_index, ob in recent_obs:
        broken = _broken_candidate(ob, formation_index, structure_m5)
        if broken is None:
            continue
        direction, broken_at_index = broken
        zone_bottom = min(float(ob.bottom), float(ob.top))
        zone_top = max(float(ob.bottom), float(ob.top))
        if not pd.isna(entry) and zone_bottom - tolerance <= entry <= zone_top + tolerance:
            candidates.append((formation_index, broken_at_index, ob, direction))
    if not candidates:
        any_broken = any(
            _broken_candidate(ob, index, structure_m5) is not None
            for index, ob in recent_obs
        )
        return _reject("no breaker retest" if any_broken else "OB not broken")

    formation_index, broken_at_index, ob, direction = max(
        candidates, key=lambda item: item[0]
    )
    h_bias_aligned = _h1_direction(h1) == direction
    if cfg.BREAKER_REQUIRE_H1_BIAS_ALIGN and not h_bias_aligned:
        return _reject("H1 bias not aligned")

    # A flipped bearish OB supports longs below its body; a flipped bullish OB
    # resists shorts above its body.
    if direction == "long":
        sl = float(ob.bottom) - cfg.SL_BUFFER_PIPS * pip
        risk = entry - sl
        tp1 = entry + risk
        tp_final = entry + 2.0 * risk
    else:
        sl = float(ob.top) + cfg.SL_BUFFER_PIPS * pip
        risk = sl - entry
        tp1 = entry - risk
        tp_final = entry - 2.0 * risk
    if risk <= 0 or risk / pip < cfg.BREAKER_MIN_RISK_PIPS:
        return _reject("risk below minimum")

    tags = build_ict_tags(
        tf_data,
        direction,
        float(ob.bottom),
        float(ob.top),
        forced_fvg_ob=True,
    )
    tags["h_bias_aligned"] = h_bias_aligned

    signal = {
        "direction": direction,
        "pattern": PATTERN,
        "entry": float(entry),
        "sl": float(sl),
        "tp1": float(tp1),
        "tp_final": float(tp_final),
        "meta": {
            "ob_top": float(ob.top),
            "ob_bottom": float(ob.bottom),
            "broken_at_index": int(broken_at_index),
            **tags,
        },
    }
    stats.record(NAME, "EMIT")
    log.info(
        "breaker_flip candidate %s entry=%s sl=%s tp1=%s tp_final=%s",
        direction, entry, sl, tp1, tp_final,
    )
    return signal


register(SetupSpec(
    name=NAME,
    scan=scan,
    killzone_mode="preferred",
    killzones=("LONDON", "NY_AM"),
    cooldown_seconds=3600,
))
