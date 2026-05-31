"""
Tier SWING — Break & Retest of S/R polarity (H4/D1).

DIFFERENT REGIME from the scalp tiers: trades last hours, wider stops.
Still respects the shared scanner contract (same returned dict schema).

Document Setup 2:
  - Horizontal S/R level on H4/D1 with >= SR_MIN_REJECTIONS prior rejections
  - H4 candle CLOSES decisively beyond the level, with volume > factor * MA(volume)
  - Price returns (retest) to the broken level, now flipped in polarity
  - M15 rejection/engulfing candle confirms → entry
  - TP = next opposite H4 structure level; RR >= SWING_RR_MIN

estimated_winrate = 0.58 is UNVALIDATED — needs backtest.
"""
import logging
import pandas as pd

from indicators import find_swings, determine_bias
from config import cfg

log = logging.getLogger(__name__)


def _find_sr_levels(df: pd.DataFrame, tol_pips: float, min_rejections: int) -> list[float]:
    """
    Cluster swing highs/lows into horizontal S/R levels. A level is valid if at
    least `min_rejections` swings cluster within `tol_pips` of it.
    Returns a list of level prices (cluster means).
    """
    tol = tol_pips * 0.10
    swings = find_swings(df, lookback=cfg.SWING_LOOKBACK)
    prices = sorted(s.price for s in swings)
    if not prices:
        return []

    levels: list[float] = []
    cluster: list[float] = [prices[0]]
    for p in prices[1:]:
        if abs(p - cluster[-1]) <= tol:
            cluster.append(p)
        else:
            if len(cluster) >= min_rejections:
                levels.append(sum(cluster) / len(cluster))
            cluster = [p]
    if len(cluster) >= min_rejections:
        levels.append(sum(cluster) / len(cluster))
    return levels


def _volume_ma(df: pd.DataFrame, period: int) -> float | None:
    if "volume" not in df.columns or len(df) < period + 1:
        return None
    window = df["volume"].iloc[-(period + 1):-1]
    if window.empty:
        return None
    return float(window.mean())


def _safe_rr(target: float, entry_mid: float, sl: float) -> float | None:
    denom = abs(entry_mid - sl)
    if denom < 0.01:
        return None
    return abs(target - entry_mid) / denom


def scan_break_retest(
    tf_data: dict[str, pd.DataFrame],
    direction: str = "LONG",
) -> dict | None:
    d1 = tf_data.get("D1")
    h4 = tf_data.get("H4")
    m15 = tf_data.get("M15")
    if d1 is None or h4 is None or m15 is None or d1.empty or h4.empty or m15.empty:
        return None

    expected = "BULLISH" if direction == "LONG" else "BEARISH"

    # S/R levels from D1 + H4 combined.
    levels = _find_sr_levels(d1, cfg.SR_TOLERANCE_PIPS, cfg.SR_MIN_REJECTIONS)
    levels += _find_sr_levels(h4, cfg.SR_TOLERANCE_PIPS, cfg.SR_MIN_REJECTIONS)
    if not levels:
        return None

    # Use the last CLOSED H4 candle for the breakout test (iloc[-2]).
    if len(h4) < 2:
        return None
    breakout = h4.iloc[-2]
    prev = h4.iloc[-3] if len(h4) >= 3 else h4.iloc[-2]

    vol_ma = _volume_ma(h4, cfg.SR_VOLUME_MA_PERIOD)
    if vol_ma is None:
        return None
    if "volume" not in h4.columns or breakout["volume"] <= cfg.SR_VOLUME_FACTOR * vol_ma:
        return None

    # Find a level that was broken by the breakout candle in the trade direction.
    broken_level = None
    for lvl in levels:
        if direction == "LONG":
            # close above resistance, previous close below it
            if prev["close"] <= lvl < breakout["close"]:
                broken_level = lvl
                break
        else:
            if prev["close"] >= lvl > breakout["close"]:
                broken_level = lvl
                break
    if broken_level is None:
        return None

    # Retest: current price back near the broken level (now flipped polarity).
    current_price = m15.iloc[-1]["close"]
    tol = cfg.SR_TOLERANCE_PIPS * 0.10
    if abs(current_price - broken_level) > tol * 3:
        return None

    # M15 rejection/engulfing confirmation on the last CLOSED candle.
    if len(m15) < 2:
        return None
    conf = m15.iloc[-2]
    body = abs(conf["close"] - conf["open"])
    rng = conf["high"] - conf["low"]
    if rng <= 0:
        return None
    if direction == "LONG":
        lower_wick = min(conf["open"], conf["close"]) - conf["low"]
        rejection = lower_wick > body and conf["close"] > conf["open"]
    else:
        upper_wick = conf["high"] - max(conf["open"], conf["close"])
        rejection = upper_wick > body and conf["close"] < conf["open"]
    if not rejection:
        return None

    # TP = next opposite H4 structure level beyond the entry.
    h4_swings = find_swings(h4, lookback=cfg.SWING_LOOKBACK)
    if direction == "LONG":
        tp = max((s.price for s in h4_swings if s.type == "HIGH" and s.price > current_price),
                 default=current_price * 1.01)
        sl = broken_level - cfg.SR_SL_BUFFER_PIPS * 0.10
    else:
        tp = min((s.price for s in h4_swings if s.type == "LOW" and s.price < current_price),
                 default=current_price * 0.99)
        sl = broken_level + cfg.SR_SL_BUFFER_PIPS * 0.10

    entry_low = min(conf["low"], broken_level)
    entry_high = max(conf["high"], broken_level)
    mid = current_price
    rr = _safe_rr(tp, mid, sl)
    if rr is None or rr < cfg.SWING_RR_MIN:
        return None

    confluences = ["SR_Level", "Breakout_Volume", "Polarity_Retest", "Rejection_Candle"]
    score = min(10, len(confluences) * 2)

    return {
        "tier": "SWING",
        "direction": direction,
        "pattern": "Break & Retest S/R",
        "killzone": "SWING",
        "entry_zone_low": round(entry_low, 2),
        "entry_zone_high": round(entry_high, 2),
        "stop_loss": round(sl, 2),
        "take_profit": round(tp, 2),
        "bias_h4": expected,   # SWING has no separate H1 gate; bias derived from setup
        "bias_h1": expected,
        "confluences": confluences,
        "confluence_score": score,
        "estimated_winrate": 0.58,
    }