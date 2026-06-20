"""Unit tests for detector — no MT5 required."""
import sys
import os
import unittest.mock as mock
from datetime import datetime, timezone

import pandas as pd
import pytest

# Make detector importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "detector"))


# ── FVG tests ──────────────────────────────────────────────────────────────────

from indicators.fvg import detect_fvg, FVG


def _make_df(rows: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(rows)
    df["time"] = pd.to_datetime(df.get("time", [datetime.now(tz=timezone.utc)] * len(df)))
    return df


def test_bullish_fvg_detected():
    # 4 candles required: c1/c2/c3 form the FVG, c4 is the current forming candle (excluded).
    df = _make_df([
        {"open": 100, "high": 101, "low": 99,  "close": 100},  # c1
        {"open": 101, "high": 105, "low": 100, "close": 104},  # c2 impulse up
        {"open": 104, "high": 106, "low": 102, "close": 105},  # c3 — low 102 > c1 high 101 ✓
        {"open": 105, "high": 107, "low": 104, "close": 106},  # c4 forming (excluded)
    ])
    fvgs = detect_fvg(df, min_size_pips=1.0)
    assert len(fvgs) == 1
    assert fvgs[0].type == "BULLISH"
    assert fvgs[0].bottom == pytest.approx(101.0)
    assert fvgs[0].top == pytest.approx(102.0)


def test_bearish_fvg_detected():
    # 4 candles required: c1/c2/c3 form the FVG, c4 is the current forming candle (excluded).
    df = _make_df([
        {"open": 105, "high": 106, "low": 104, "close": 105},  # c1
        {"open": 104, "high": 104, "low": 100, "close": 101},  # c2 impulse down
        {"open": 101, "high": 103, "low": 100, "close": 100},  # c3 — high 103 < c1 low 104 ✓
        {"open": 100, "high": 101, "low": 99,  "close": 100},  # c4 forming (excluded)
    ])
    fvgs = detect_fvg(df, min_size_pips=1.0)
    assert len(fvgs) == 1
    assert fvgs[0].type == "BEARISH"


def test_no_fvg_when_candles_overlap():
    df = _make_df([
        {"open": 100, "high": 103, "low": 99,  "close": 102},
        {"open": 102, "high": 105, "low": 101, "close": 104},
        {"open": 104, "high": 106, "low": 102, "close": 105},  # c3 low 102 == c1 high 103 — no gap
    ])
    fvgs = detect_fvg(df, min_size_pips=1.0)
    assert len(fvgs) == 0


def test_fvg_too_small_filtered():
    df = _make_df([
        {"open": 100, "high": 100.5, "low": 99, "close": 100},
        {"open": 100.5, "high": 103, "low": 100, "close": 102},
        {"open": 102, "high": 104, "low": 100.7, "close": 103},  # gap = 0.2 pips
    ])
    fvgs = detect_fvg(df, min_size_pips=3.0)
    assert len(fvgs) == 0


# ── Structure tests ────────────────────────────────────────────────────────────

from indicators.structure import find_swings


# ── Fibonacci tests ────────────────────────────────────────────────────────────

from indicators.fibonacci import FibLevels, compute_fib_from_sweep


def test_ote_zone_bullish():
    fib = compute_fib_from_sweep(sweep_low=1800.0, swing_high=1900.0)
    # OTE zone for BULLISH retracement (range=100):
    #   upper bound (0.618): 1900 - 61.8 = 1838.2
    #   lower bound (0.786): 1900 - 78.6 = 1821.4
    # 1840.0 is ABOVE the zone (59% retracement — too shallow) — original test was wrong.
    assert fib.is_in_ote(1830.0)         # 70% retracement — inside OTE ✓
    assert not fib.is_in_ote(1870.0)     # 30% retracement — above OTE (too shallow)
    assert not fib.is_in_ote(1810.0)     # 90% retracement — below OTE (too deep)


def test_equilibrium():
    fib = FibLevels(swing_high=2000, swing_low=1800, direction="BULLISH")
    assert fib.equilibrium == pytest.approx(1900.0)


# ── Killzone tests ─────────────────────────────────────────────────────────────

from strategy.killzone import get_active_killzone, minutes_to_next_killzone
import pytz


def test_ny_am_killzone():
    ny = pytz.timezone("America/New_York")
    assert get_active_killzone(ny.localize(datetime(2024, 1, 15, 8, 30))) == "NY_AM"
    assert get_active_killzone(ny.localize(datetime(2024, 1, 15, 8, 29))) is None


def test_london_killzone_dst_correct():
    summer = datetime(2024, 7, 15, 7, 0, tzinfo=pytz.utc)  # 03:00 EDT
    winter = datetime(2024, 1, 15, 8, 0, tzinfo=pytz.utc)  # 03:00 EST
    assert get_active_killzone(summer) == "LONDON"
    assert get_active_killzone(winter) == "LONDON"


def test_outside_killzone():
    dt = datetime(2024, 1, 15, 17, 0, tzinfo=pytz.utc)  # 12:00 EST = dead zone
    kz = get_active_killzone(dt)
    assert kz is None


def test_disabled_killzone_is_filtered(monkeypatch):
    from config import cfg

    monkeypatch.setattr(cfg, "ENABLED_KILLZONES", ["LONDON", "NY_AM"])
    ny_pm = datetime(2024, 1, 15, 19, 0, tzinfo=pytz.utc)  # 14:00 EST
    assert get_active_killzone(ny_pm) is None


def test_minutes_to_next_killzone_uses_ny_minutes():
    before_ny_am = datetime(2024, 1, 15, 13, 29, tzinfo=pytz.utc)  # 08:29 EST
    assert minutes_to_next_killzone(before_ny_am) == 1


# ── Webhook signing test ───────────────────────────────────────────────────────

from webhook import _sign


def test_hmac_sign_deterministic():
    payload = b'{"tier": "S", "direction": "LONG"}'
    sig1 = _sign(payload, "test-secret-key-32chars-abcdefgh")
    sig2 = _sign(payload, "test-secret-key-32chars-abcdefgh")
    assert sig1 == sig2


def test_hmac_sign_different_secret():
    payload = b'{"tier": "S"}'
    sig1 = _sign(payload, "secret-aaa")
    sig2 = _sign(payload, "secret-bbb")
    assert sig1 != sig2


# ── Structure break / CHoCH regression tests ──────────────────────────────────

from indicators.structure import (
    find_swings, get_recent_structure_break, Swing,
)


def _make_trending_df_with_break() -> tuple[pd.DataFrame, list[Swing]]:
    """
    200 candles of a BULLISH trend followed by a clear bullish structure break
    in the last 10 candles.  The final swing high is broken by the last candle.

    Layout (prices):
      candles 0-189: zigzag around 3300 — establishes swings with positional
                     indices 0-189 in the FULL df.
      candle 190:    swing high at 3320 (the level that will be broken)
      candles 191-198: retrace to ~3310
      candle 199:    closes at 3325, breaking above the 3320 swing high → BOS/break
    """
    rows = []
    base = 3300.0
    # Build 190 candles of zigzag
    for i in range(190):
        wave = 5.0 * (1 if (i // 5) % 2 == 0 else -1)
        p = base + wave + i * 0.01  # slight upward drift
        rows.append({"open": p, "high": p + 2, "low": p - 2, "close": p})
    # candle 190: local swing high at 3320
    rows.append({"open": 3318, "high": 3322, "low": 3316, "close": 3319})
    # candles 191-198: retrace
    for j in range(8):
        p = 3310.0 - j * 0.1
        rows.append({"open": p, "high": p + 1, "low": p - 1, "close": p})
    # candle 199: breaks above 3320 closing at 3325
    rows.append({"open": 3320, "high": 3326, "low": 3319, "close": 3325})

    df = _make_df(rows)
    swings = find_swings(df, lookback=3)
    return df, swings


def test_structure_break_in_bias_direction_detected():
    """The runtime helper finds a recent bullish structure break."""
    df, swings = _make_trending_df_with_break()

    # New function: must find the bullish break in the last 15 candles.
    sb = get_recent_structure_break(df, swings, "BULLISH", lookback_candles=15)
    assert sb is not None, "get_recent_structure_break should detect the bullish break"
    assert sb.direction == "BULLISH"


def test_sfp_ote_geometry():
    """
    Documents the shared bullish OTE geometry.

    Setup: leg low=3300, leg high=3320 (range=20).
    BULLISH OTE zone: 0.618–0.786 retracement FROM swing_high DOWN.
      upper bound (0.618): 3320 - 20*0.618 = 3307.64
      lower bound (0.786): 3320 - 20*0.786 = 3304.28
    """
    from indicators.fibonacci import compute_fib_from_sweep, compute_fib_from_sweep_bearish

    leg_low, leg_high = 3300.0, 3320.0

    # Correct anchoring: leg_low → leg_high
    fib = compute_fib_from_sweep(leg_low, leg_high, ote_low=0.618, ote_high=0.786)
    assert fib.is_in_ote(3305.0), "3305.0 should be inside OTE [3304.28, 3307.64]"
    assert not fib.is_in_ote(3298.0), "3298.0 is below the sweep low — outside OTE"
    assert not fib.is_in_ote(3315.0), "3315.0 is too shallow a retracement — above OTE"

    # Old (broken) anchoring: fib from asia_low=3306 to swing_h=3320 (range=14).
    # OTE zone: [3320-14*0.786, 3320-14*0.618] = [3308.996, 3311.348]
    # The sweep_wick (< 3306 by definition) can never be >= 3308.996 → always False.
    fib_old = compute_fib_from_sweep(3306.0, 3320.0, ote_low=0.618, ote_high=0.786)
    # Any wick below asia_low (3306) should fail the old check
    for wick in [3305.0, 3303.0, 3298.0]:
        assert not fib_old.is_in_ote(wick), (
            f"OLD anchoring: sweep_wick={wick} (below asia_low=3306) must fail "
            f"is_in_ote — documents why the original check was dead"
        )


def test_eurusd_order_block_body_threshold():
    """A normal EURUSD M5 body survives the symbol-relative one-pip doji filter."""
    from config import Config
    from indicators.order_block import detect_order_blocks

    original_pip = Config.PIP
    Config.PIP = 0.0001
    try:
        rows = [
            {"open": 1.1000, "high": 1.1002, "low": 1.0998, "close": 1.1000}
            for _ in range(35)
        ]
        rows[30] = {"open": 1.1005, "high": 1.1006, "low": 1.1000, "close": 1.1002}
        rows[31] = {"open": 1.1003, "high": 1.1010, "low": 1.1002, "close": 1.1009}
        rows[32] = {"open": 1.1009, "high": 1.1012, "low": 1.1008, "close": 1.1011}

        obs = detect_order_blocks(_make_df(rows), lookback=30)

        assert any(ob.type == "BULLISH" for ob in obs)
    finally:
        Config.PIP = original_pip


# ── Stats module tests ─────────────────────────────────────────────────────────

def test_stats_counters(caplog):
    """record/tick smoke test: counters increment, summary logs at the every boundary."""
    import logging
    import stats as stats_mod

    # Reset module state
    stats_mod._counters.clear()
    stats_mod._scan_count = 0

    stats_mod.record("test_scanner", "EMIT")
    stats_mod.record("test_scanner", "no_sweep")
    stats_mod.record("test_scanner", "no_sweep")

    assert stats_mod._counters["test_scanner"]["EMIT"] == 1
    assert stats_mod._counters["test_scanner"]["no_sweep"] == 2

    with caplog.at_level(logging.INFO, logger="stats"):
        for _ in range(119):
            stats_mod.tick(every=120)
        assert not any("SCAN_STATS" in r.message for r in caplog.records), (
            "Summary must NOT fire before the 120th tick"
        )
        stats_mod.tick(every=120)
        assert any("SCAN_STATS" in r.message for r in caplog.records), (
            "Summary MUST fire at the 120th tick"
        )
