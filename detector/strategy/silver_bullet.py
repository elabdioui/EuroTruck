import logging
from zoneinfo import ZoneInfo

import pandas as pd

import stats
from config import cfg
from indicators.bias import ema
from indicators.fvg import detect_fvg
from ._bars import closed
from .ict_tags import build_ict_tags
from .registry import SetupSpec, register


NAME = "silver_bullet"
PATTERN = "ny_am_fvg_mitigation"

log = logging.getLogger(__name__)
_NY_TZ = ZoneInfo("America/New_York")


def _reject(reason: str) -> None:
    log.debug("silver_bullet reject: %s", reason)
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


def _h1_bias(h1: pd.DataFrame) -> tuple[str, float]:
    average = ema(h1["close"], 20).iloc[-1]
    close = pd.to_numeric(h1["close"], errors="coerce").iloc[-1]
    if pd.isna(average) or pd.isna(close) or close == average:
        return "flat", float(average)
    return ("long" if close > average else "short"), float(average)


def scan(tf_data: dict) -> dict | None:
    m5 = tf_data.get("M5")
    h1 = tf_data.get("H1")
    if (
        not isinstance(m5, pd.DataFrame)
        or not isinstance(h1, pd.DataFrame)
        or len(m5) < 100
        or len(h1) < 30
        or not {"high", "low", "close"}.issubset(m5.columns)
        or "close" not in h1.columns
    ):
        return _reject("insufficient data")

    m5c = closed(m5)
    h1c = closed(h1)

    m5_times = _timestamps(m5c)
    if m5_times is None:
        return _reject("insufficient data")
    ny_now = m5_times[-1].tz_convert(_NY_TZ)
    if not (
        cfg.SILVER_BULLET_NY_START_HOUR
        <= ny_now.hour
        < cfg.SILVER_BULLET_NY_END_HOUR
    ):
        return _reject(f"outside silver bullet window (NY hour={ny_now.hour})")

    pip = float(cfg.PIP)
    if pip <= 0:
        return _reject("invalid pip size")
    structure_m5 = m5c.copy()
    structure_m5["time"] = m5_times
    fvgs = detect_fvg(structure_m5, min_size_pips=0.0)
    window_start = ny_now.normalize() + pd.Timedelta(
        hours=cfg.SILVER_BULLET_NY_START_HOUR
    )
    window_fvgs = []
    for fvg in fvgs:
        formed_at = pd.Timestamp(fvg.time)
        if formed_at.tzinfo is None:
            formed_at = formed_at.tz_localize("UTC")
        formed_ny = formed_at.tz_convert(_NY_TZ)
        if (
            window_start <= formed_ny <= ny_now
            and fvg.size / pip >= cfg.FVG_MIN_SIZE_PIPS
        ):
            window_fvgs.append(fvg)
    if not window_fvgs:
        return _reject("no FVG in window")
    fvg = window_fvgs[-1]

    current_price = float(pd.to_numeric(m5c["close"], errors="coerce").iloc[-1])
    zone_low = min(float(fvg.bottom), float(fvg.top))
    zone_high = max(float(fvg.bottom), float(fvg.top))
    if pd.isna(current_price) or not zone_low <= current_price <= zone_high:
        return _reject("FVG not mitigated yet")

    direction = "long" if fvg.type == "BULLISH" else "short"
    entry = (float(fvg.top) + float(fvg.bottom)) / 2.0
    if direction == "long":
        sl = float(fvg.bottom) - cfg.SL_BUFFER_PIPS * pip
        risk = entry - sl
        tp1 = entry + risk
        tp_final = entry + 2.0 * risk
    else:
        sl = float(fvg.top) + cfg.SL_BUFFER_PIPS * pip
        risk = sl - entry
        tp1 = entry - risk
        tp_final = entry - 2.0 * risk
    if risk <= 0 or risk / pip < cfg.SILVER_BULLET_MIN_RISK_PIPS:
        return _reject("risk below minimum")

    h1_bias, _ = _h1_bias(h1c)
    tags = build_ict_tags(
        tf_data,
        direction,
        float(fvg.bottom),
        float(fvg.top),
        forced_fvg_ob=True,
    )
    tags["h_bias_aligned"] = h1_bias == direction
    if cfg.SILVER_BULLET_REQUIRE_BIAS and not tags["h_bias_aligned"]:
        return _reject("H1 bias not aligned")
    signal = {
        "direction": direction,
        "pattern": PATTERN,
        "entry": float(entry),
        "sl": float(sl),
        "tp1": float(tp1),
        "tp_final": float(tp_final),
        "meta": {
            "fvg_top": float(fvg.top),
            "fvg_bottom": float(fvg.bottom),
            "ny_hour": int(ny_now.hour),
            "h1_bias": h1_bias,
            **tags,
        },
    }
    stats.record(NAME, "EMIT")
    log.info(
        "silver_bullet candidate %s entry=%s sl=%s tp1=%s tp_final=%s",
        direction, entry, sl, tp1, tp_final,
    )
    return signal


register(SetupSpec(
    name=NAME,
    scan=scan,
    killzone_mode="required",
    killzones=("NY_AM",),
    cooldown_seconds=1800,
))
