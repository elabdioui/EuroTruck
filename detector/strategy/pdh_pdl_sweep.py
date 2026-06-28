import logging

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


NAME = "pdh_pdl_sweep"
PATTERN = "pd_liquidity_sweep_reversal"

log = logging.getLogger(__name__)


def _reject(reason: str) -> None:
    log.debug("pdh_pdl_sweep reject: %s", reason)
    stats.record(NAME, reason)
    return None


def _has_columns(frame: pd.DataFrame, columns: set[str]) -> bool:
    return columns.issubset(frame.columns)


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


def _is_rejection(candle: pd.Series) -> bool:
    candle_range = float(candle["high"]) - float(candle["low"])
    if candle_range <= 0:
        return False
    body_ratio = abs(float(candle["close"]) - float(candle["open"])) / candle_range
    return body_ratio <= cfg.PDH_PDL_WICK_BODY_RATIO_MAX


def _find_sweep(
    frame: pd.DataFrame, pdh: float, pdl: float
) -> tuple[str, int, float] | None:
    start = len(frame) - cfg.PDH_PDL_LOOKBACK_M5
    recent = frame.iloc[start:]
    candidates: list[tuple[str, int, float]] = []

    long_offset = int(recent["low"].to_numpy().argmin())
    long_candle = recent.iloc[long_offset]
    if (
        float(long_candle["low"]) < pdl
        and float(long_candle["close"]) > pdl
        and _is_rejection(long_candle)
    ):
        candidates.append(("long", start + long_offset, float(long_candle["low"])))

    short_offset = int(recent["high"].to_numpy().argmax())
    short_candle = recent.iloc[short_offset]
    if (
        float(short_candle["high"]) > pdh
        and float(short_candle["close"]) < pdh
        and _is_rejection(short_candle)
    ):
        candidates.append(("short", start + short_offset, float(short_candle["high"])))

    return max(candidates, key=lambda candidate: candidate[1]) if candidates else None


def scan(tf_data: dict) -> dict | None:
    d1 = tf_data.get("D1")
    m5 = tf_data.get("M5")
    if (
        not isinstance(d1, pd.DataFrame)
        or not isinstance(m5, pd.DataFrame)
        or len(d1) < 5
        or len(m5) < 100
        or not _has_columns(d1, {"high", "low"})
        or not _has_columns(m5, {"open", "high", "low", "close"})
    ):
        return _reject("insufficient data")

    m5c = closed(m5)

    numeric_d1 = d1[["high", "low"]].apply(pd.to_numeric, errors="coerce")
    numeric_m5 = m5c[["open", "high", "low", "close"]].apply(
        pd.to_numeric, errors="coerce"
    )
    if numeric_d1.isna().any().any() or numeric_m5.isna().any().any():
        return _reject("insufficient data")

    pdh = float(numeric_d1.iloc[-2]["high"])
    pdl = float(numeric_d1.iloc[-2]["low"])
    sweep = _find_sweep(numeric_m5, pdh, pdl)
    if sweep is None:
        return _reject("no PD sweep")
    direction, sweep_index, sweep_wick = sweep

    structure_m5 = _with_time_column(m5c)
    if structure_m5 is None:
        return _reject("insufficient data")
    swings = find_swings(structure_m5, lookback=cfg.SWING_LOOKBACK)
    bos_direction = "BULLISH" if direction == "long" else "BEARISH"
    bos = get_recent_structure_break(
        structure_m5, swings, bos_direction, lookback_candles=15
    )
    if (
        bos is None
        or bos.candle_idx <= sweep_index
        or bos.candle_idx > sweep_index + 15
    ):
        return _reject("no reversal BOS")

    displacement = numeric_m5.iloc[sweep_index:bos.candle_idx + 1]
    if direction == "long":
        swing_extreme = float(displacement["high"].max())
        if swing_extreme <= sweep_wick:
            return _reject("outside entry zone")
        fib = compute_fib_from_sweep(
            sweep_wick, swing_extreme, cfg.OTE_LOW, cfg.OTE_HIGH
        )
    else:
        swing_extreme = float(displacement["low"].min())
        if swing_extreme >= sweep_wick:
            return _reject("outside entry zone")
        fib = compute_fib_from_sweep_bearish(
            sweep_wick, swing_extreme, cfg.OTE_LOW, cfg.OTE_HIGH
        )

    pip = float(cfg.PIP)
    if pip <= 0:
        return _reject("invalid pip size")
    entry = float(numeric_m5.iloc[-1]["close"])
    tolerance = cfg.OTE_ENTRY_TOLERANCE_PIPS * pip
    entry_low = min(fib.ote_low, fib.ote_high) - tolerance
    entry_high = max(fib.ote_low, fib.ote_high) + tolerance
    if not entry_low <= entry <= entry_high:
        return _reject("outside entry zone")

    if direction == "long":
        sl = sweep_wick - cfg.SL_BUFFER_PIPS * pip
        risk = entry - sl
        tp1 = entry + risk
        tp_final = entry + 2.0 * risk
    else:
        sl = sweep_wick + cfg.SL_BUFFER_PIPS * pip
        risk = sl - entry
        tp1 = entry - risk
        tp_final = entry - 2.0 * risk
    if risk <= 0 or risk / pip < cfg.PDH_PDL_MIN_RISK_PIPS:
        return _reject("risk below minimum")

    tags = build_ict_tags(
        tf_data,
        direction,
        entry_low,
        entry_high,
        swept_level=pdl if direction == "long" else pdh,
    )
    if cfg.PDH_PDL_REQUIRE_BIAS and not tags["h_bias_aligned"]:
        return _reject("HTF bias not aligned")
    if cfg.PDH_PDL_REQUIRE_FVG_OB and not tags["fvg_ob_confluence"]:
        return _reject("no FVG/OB confluence in entry zone")

    signal = {
        "direction": direction,
        "pattern": PATTERN,
        "entry": float(entry),
        "sl": float(sl),
        "tp1": float(tp1),
        "tp_final": float(tp_final),
        "meta": {
            "pdh": pdh,
            "pdl": pdl,
            "sweep_wick": float(sweep_wick),
            **tags,
        },
    }
    stats.record(NAME, "EMIT")
    log.info(
        "pdh_pdl_sweep candidate %s entry=%s sl=%s tp1=%s tp_final=%s",
        direction, entry, sl, tp1, tp_final,
    )
    return signal


register(SetupSpec(
    name=NAME,
    scan=scan,
    killzone_mode="required",
    killzones=("LONDON", "NY_AM", "NY_PM"),
    cooldown_seconds=3600,
))
