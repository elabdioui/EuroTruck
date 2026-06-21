import logging

import pandas as pd

import stats
from config import cfg
from indicators.bias import ema
from indicators.fibonacci import (
    compute_fib_from_sweep,
    compute_fib_from_sweep_bearish,
)
from indicators.fvg import detect_fvg
from indicators.order_block import detect_order_blocks
from indicators.structure import find_swings, get_recent_structure_break
from .killzone import get_session_window_utc
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


def _find_sweep(
    recent: pd.DataFrame, asia_low: float, asia_high: float
) -> tuple[str, int, float] | None:
    """Return the latest single-candle sweep rejection in ``recent``."""
    for position in range(len(recent) - 1, -1, -1):
        bar = recent.iloc[position]
        low = float(bar["low"])
        high = float(bar["high"])
        close = float(bar["close"])
        if low < asia_low <= close:
            return "long", position, low
        if high > asia_high >= close:
            return "short", position, high
    return None


def _ote_confluence(
    frame: pd.DataFrame, direction: str, ote_low: float, ote_high: float
) -> tuple[str, float, float] | None:
    expected_type = "BULLISH" if direction == "long" else "BEARISH"
    zones = [
        ("FVG", float(item.bottom), float(item.top))
        for item in detect_fvg(frame, min_size_pips=cfg.FVG_MIN_SIZE_PIPS)
        if item.type == expected_type
    ]
    zones.extend(
        ("OB", float(item.bottom), float(item.top))
        for item in detect_order_blocks(frame, lookback=cfg.OB_LOOKBACK)
        if item.type == expected_type
    )
    for kind, bottom, top in reversed(zones):
        zone_low, zone_high = sorted((bottom, top))
        if zone_low <= ote_high and zone_high >= ote_low:
            return kind, zone_low, zone_high
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
        or len(h4) < max(30, cfg.LONDON_JUDAS_BIAS_EMA + 1)
        or not _has_market_columns(m15)
        or not _has_market_columns(m5)
        or "close" not in h4.columns
    ):
        return _reject("insufficient data")

    # MT5 includes the current forming candle as the final row on every timeframe.
    m15c = m15.iloc[:-1]
    m5c = m5.iloc[:-1]
    h4c = h4.iloc[:-1]

    m15_times = _timestamps(m15c)
    m5_times = _timestamps(m5c)
    if m15_times is None or m5_times is None or pd.isna(m5_times[-1]):
        return _reject("missing UTC timestamps")

    session_start, session_end = get_session_window_utc("ASIA", m5_times[-1].to_pydatetime())
    asia = m15c.loc[(m15_times >= session_start) & (m15_times < session_end)]
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

    recent = m5c.iloc[-cfg.LONDON_JUDAS_LOOKBACK_M5:]
    sweep = _find_sweep(recent, asia_low, asia_high)
    if sweep is None:
        return _reject("no asia sweep rejection candle")
    direction, sweep_position, sweep_extreme = sweep
    sweep_index = len(m5c) - len(recent) + sweep_position

    h4_average = ema(h4c["close"], cfg.LONDON_JUDAS_BIAS_EMA).iloc[-1]
    h4_close = pd.to_numeric(h4c["close"], errors="coerce").iloc[-1]
    if pd.isna(h4_average) or pd.isna(h4_close):
        return _reject("insufficient H4 bias data")
    h4_bias = "long" if h4_close > h4_average else "short"
    if cfg.LONDON_JUDAS_REQUIRE_H4_BIAS and direction != h4_bias:
        return _reject(f"sweep {direction} against H4 bias {h4_bias}")

    structure_m5 = m5c
    if "time" not in structure_m5.columns:
        structure_m5 = m5c.copy()
        structure_m5["time"] = m5_times
    swings = find_swings(structure_m5, lookback=cfg.SWING_LOOKBACK)
    bos_direction = "BULLISH" if direction == "long" else "BEARISH"
    bos = get_recent_structure_break(
        structure_m5, swings, bos_direction, lookback_candles=20
    )
    if bos is None or bos.candle_idx <= sweep_index:
        return _reject(f"no {direction} M5 structure break")

    anchor_type = "LOW" if direction == "long" else "HIGH"
    anchors = [
        swing for swing in swings
        if swing.type == anchor_type and swing.index < bos.candle_idx
    ]
    if not anchors:
        return _reject(f"no confirmed {direction} BOS anchor")
    anchor = anchors[-1]

    displacement = m5c.iloc[anchor.index:]
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

    entry = float(m5c.iloc[-1]["close"])
    tolerance = cfg.OTE_ENTRY_TOLERANCE_PIPS * pip
    ote_low = min(fib.ote_low, fib.ote_high) - tolerance
    ote_high = max(fib.ote_low, fib.ote_high) + tolerance
    if not ote_low <= entry <= ote_high:
        return _reject("current price outside OTE zone")

    confluence = _ote_confluence(structure_m5, direction, ote_low, ote_high)
    if cfg.LONDON_JUDAS_REQUIRE_FVG_OB and confluence is None:
        return _reject("no FVG/OB confluence in OTE zone")

    if direction == "long":
        sl = min(float(anchor.price), sweep_extreme) - cfg.SL_BUFFER_PIPS * pip
        risk = entry - sl
        tp1 = entry + risk
        tp_final = entry + 2.0 * risk
    else:
        sl = max(float(anchor.price), sweep_extreme) + cfg.SL_BUFFER_PIPS * pip
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
            "h4_bias": h4_bias,
            "sweep_index": sweep_index,
            "sweep_extreme": sweep_extreme,
            "ote_confluence": confluence[0] if confluence else None,
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
