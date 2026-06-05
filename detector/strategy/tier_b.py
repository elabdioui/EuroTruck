"""Tier B setups: Breaker+Fib, BOS+FVG retest."""
import logging
import pandas as pd

from indicators import (
    detect_fvg, filter_unfilled_fvg, get_recent_fvg,
    detect_order_blocks, update_mitigation,
    find_swings, determine_bias, detect_structure_breaks,
    compute_fib_from_sweep, compute_fib_from_sweep_bearish,
    find_liquidity_target, find_liquidity_pools, detect_sweeps, detect_regime,
)
from strategy.killzone import get_active_killzone
from strategy.scoring import _score_confluences
from config import cfg

log = logging.getLogger(__name__)


def _safe_rr(target: float, entry_mid: float, sl: float) -> float | None:
    """Risk-reward with a divide-by-zero guard. Returns None if SL == entry."""
    denom = abs(entry_mid - sl)
    if denom < 0.01:
        return None
    return abs(target - entry_mid) / denom


def scan_breaker_fib(
    tf_data: dict[str, pd.DataFrame],
    direction: str = "LONG",
) -> dict | None:
    """
    Breaker Block + Fib confluence:
    - LONG: former BEARISH OB broken upward → acts as bullish support breaker
    - SHORT: former BULLISH OB broken downward → acts as bearish resistance breaker
    - Price retraces into the breaker zone and sits within the OTE Fib range
    """
    killzone = get_active_killzone()
    if killzone is None:
        return None

    m5 = tf_data.get("M5")
    h4 = tf_data.get("H4")
    if m5 is None or h4 is None or m5.empty or h4.empty:
        return None

    if detect_regime(m5, cfg.REGIME_ATR_PERIOD, cfg.REGIME_VOL_MULTIPLIER, cfg.REGIME_RANGE_MULTIPLIER) != "trend":
        return None

    h4_swings = find_swings(h4, lookback=cfg.SWING_LOOKBACK)
    h4_bias = determine_bias(h4_swings)
    expected = "BULLISH" if direction == "LONG" else "BEARISH"
    if h4_bias != expected:
        return None

    current_price = m5.iloc[-1]["close"]

    m5_obs = detect_order_blocks(m5, lookback=cfg.OB_LOOKBACK)
    m5_obs = update_mitigation(m5_obs, m5, lookback=len(m5))

    # Breaker = mitigated OB that has flipped.
    # For a LONG: a former BEARISH OB broken to the upside acts as bullish support.
    # For a SHORT: a former BULLISH OB broken to the downside acts as bearish resistance.
    opp_dir = "BEARISH" if direction == "LONG" else "BULLISH"
    breakers = [o for o in m5_obs if o.is_breaker and o.type == opp_dir]
    if not breakers:
        return None

    if direction == "LONG":
        breakers = [o for o in breakers if o.top < current_price]
    else:
        breakers = [o for o in breakers if o.bottom > current_price]
    if not breakers:
        return None

    nearest_breaker = min(breakers, key=lambda o: abs(o.mid - current_price))

    # ICT sequence: liquidity sweep must precede the OB-to-breaker flip.
    # LONG needs a prior SSL sweep; SHORT needs a prior BSL sweep.
    sweep_pool_type = "SSL" if direction == "LONG" else "BSL"
    pools = find_liquidity_pools(m5, swing_lookback=cfg.SWING_LOOKBACK,
                                 tolerance_pips=cfg.LIQUIDITY_EQUAL_THRESHOLD)
    candidate_pools = [p for p in pools if p.type == sweep_pool_type]
    swept_pools = detect_sweeps(m5, candidate_pools, lookback_candles=len(m5))
    # Require a sweep that completed before the breaker formation.
    prior_sweep = next(
        (p for p in swept_pools
         if p.swept
         and nearest_breaker.breaker_time is not None
         and p.sweep_time is not None
         and p.sweep_time < nearest_breaker.breaker_time),
        None,
    )
    if prior_sweep is None:
        return None

    m5_swings = find_swings(m5, lookback=cfg.SWING_LOOKBACK)
    if direction == "LONG":
        swing_h = max((s.price for s in m5_swings if s.type == "HIGH"), default=None)
        if swing_h is None:
            return None
        if swing_h <= nearest_breaker.bottom:
            return None
        fib = compute_fib_from_sweep(nearest_breaker.bottom, swing_h)
    else:
        swing_l = min((s.price for s in m5_swings if s.type == "LOW"), default=None)
        if swing_l is None:
            return None
        if swing_l >= nearest_breaker.top:
            return None
        fib = compute_fib_from_sweep_bearish(nearest_breaker.top, swing_l)

    in_ote = fib.is_in_ote(current_price)
    if not in_ote:
        return None

    confluences = ["Bias_H4", "Breaker_M5", "Sweep", f"OTE_{cfg.OTE_LOW}"]

    score = _score_confluences(confluences)
    if score < cfg.MIN_SCORE_B:
        return None

    if direction == "LONG":
        sl = nearest_breaker.bottom - cfg.SL_BUFFER
        tp = find_liquidity_target(m5, direction, current_price, swing_lookback=cfg.SWING_LOOKBACK)
        if tp is None:
            tp = max((s.price for s in m5_swings if s.type == "HIGH"), default=current_price * 1.003)
    else:
        sl = nearest_breaker.top + cfg.SL_BUFFER
        tp = find_liquidity_target(m5, direction, current_price, swing_lookback=cfg.SWING_LOOKBACK)
        if tp is None:
            tp = min((s.price for s in m5_swings if s.type == "LOW"), default=current_price * 0.997)

    entry_ref = nearest_breaker.top if direction == "LONG" else nearest_breaker.bottom
    rr = _safe_rr(tp, entry_ref, sl)
    if rr is None or rr < cfg.MIN_RR:
        return None

    return {
        "tier": "B",
        "direction": direction,
        "pattern": "Breaker + OTE",
        "killzone": killzone,
        "entry_zone_low": round(nearest_breaker.bottom, 2),
        "entry_zone_high": round(nearest_breaker.top, 2),
        "stop_loss": round(sl, 2),
        "take_profit": round(tp, 2),
        "bias_h4": h4_bias,
        "bias_h1": expected,
        "confluences": confluences,
        "confluence_score": score,
        "estimated_winrate": 0.52,  # static placeholder — not a measured statistic
    }


def scan_bos_fvg(
    tf_data: dict[str, pd.DataFrame],
    direction: str = "LONG",
) -> dict | None:
    """
    BOS + FVG Retest:
    - BOS confirms direction on M5
    - FVG left by the BOS impulse (only FVGs whose middle candle is on/after
      the most recent BOS candle are considered; older FVGs are discarded)
    - Price retests the FVG
    """
    killzone = get_active_killzone()
    if killzone is None:
        return None

    m5 = tf_data.get("M5")
    h4 = tf_data.get("H4")
    if m5 is None or h4 is None or m5.empty or h4.empty:
        return None

    if detect_regime(m5, cfg.REGIME_ATR_PERIOD, cfg.REGIME_VOL_MULTIPLIER, cfg.REGIME_RANGE_MULTIPLIER) != "trend":
        return None

    h4_swings = find_swings(h4, lookback=cfg.SWING_LOOKBACK)
    h4_bias = determine_bias(h4_swings)
    expected = "BULLISH" if direction == "LONG" else "BEARISH"
    if h4_bias != expected:
        return None

    m5_swings = find_swings(m5, lookback=cfg.SWING_LOOKBACK)

    # BUGFIX: classify BOS/CHoCH against the EXPECTED (H4) bias, not the M5 bias.
    # The original passed m5_bias, which can be "NEUTRAL"; in that case
    # detect_structure_breaks never labels a break as BOS, so this setup could
    # never fire even when a valid BOS existed. Using the H4 bias as the
    # prevailing-trend reference makes BOS classification deterministic.
    breaks = detect_structure_breaks(m5, m5_swings, expected)  # type: ignore[arg-type]
    bos_list = [b for b in breaks if b.type == "BOS" and b.direction == expected]
    if not bos_list:
        return None

    latest_bos = bos_list[-1]

    # ICT sequence: SSL sweep (LONG) or BSL sweep (SHORT) must precede the BOS.
    sweep_pool_type = "SSL" if direction == "LONG" else "BSL"
    pools = find_liquidity_pools(m5, swing_lookback=cfg.SWING_LOOKBACK,
                                 tolerance_pips=cfg.LIQUIDITY_EQUAL_THRESHOLD)
    candidate_pools = [p for p in pools if p.type == sweep_pool_type]
    swept_pools = detect_sweeps(m5, candidate_pools, lookback_candles=len(m5))
    prior_sweep = next(
        (p for p in swept_pools
         if p.swept and p.sweep_time is not None and p.sweep_time < latest_bos.time),
        None,
    )
    if prior_sweep is None:
        return None

    current_price = m5.iloc[-1]["close"]
    m5_fvgs = detect_fvg(m5.iloc[-30:], min_size_pips=cfg.FVG_MIN_SIZE_PIPS)
    fvg_dir = "BULLISH" if direction == "LONG" else "BEARISH"
    m5_fvgs = filter_unfilled_fvg(m5_fvgs, current_price)
    recent_fvgs = get_recent_fvg(m5_fvgs, fvg_dir, n=2)

    # Keep only FVGs formed on/after the BOS impulse candle.
    # Use time comparison so the slice-relative candle_idx of detect_fvg
    # does not need to be remapped to the full-df absolute position.
    post_bos_fvgs = [f for f in recent_fvgs if f.time >= latest_bos.time]
    if not post_bos_fvgs:
        return None

    best_fvg = post_bos_fvgs[-1]
    in_fvg = best_fvg.bottom <= current_price <= best_fvg.top
    if not in_fvg:
        return None

    confluences = ["Bias_H4", "BOS_M5", "FVG_M5", "Sweep"]
    score = _score_confluences(confluences)
    if score < cfg.MIN_SCORE_B:
        return None

    if direction == "LONG":
        sl = best_fvg.bottom - cfg.SL_BUFFER
        tp = find_liquidity_target(m5, direction, current_price, swing_lookback=cfg.SWING_LOOKBACK)
        if tp is None:
            tp = max((s.price for s in m5_swings if s.type == "HIGH"), default=current_price * 1.003)
    else:
        sl = best_fvg.top + cfg.SL_BUFFER
        tp = find_liquidity_target(m5, direction, current_price, swing_lookback=cfg.SWING_LOOKBACK)
        if tp is None:
            tp = min((s.price for s in m5_swings if s.type == "LOW"), default=current_price * 0.997)

    entry_ref = best_fvg.top if direction == "LONG" else best_fvg.bottom
    rr = _safe_rr(tp, entry_ref, sl)
    if rr is None or rr < cfg.MIN_RR:
        return None

    return {
        "tier": "B",
        "direction": direction,
        "pattern": "BOS + FVG Retest",
        "killzone": killzone,
        "entry_zone_low": round(best_fvg.bottom, 2),
        "entry_zone_high": round(best_fvg.top, 2),
        "stop_loss": round(sl, 2),
        "take_profit": round(tp, 2),
        "bias_h4": h4_bias,
        "bias_h1": expected,
        "confluences": confluences,
        "confluence_score": score,
        "estimated_winrate": 0.50,  # static placeholder — not a measured statistic
    }