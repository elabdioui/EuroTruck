"""Unit tests for detector — no MT5 required."""
import sys
import os
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
    df = _make_df([
        {"open": 100, "high": 101, "low": 99,  "close": 100},  # c1
        {"open": 101, "high": 105, "low": 100, "close": 104},  # c2 impulse up
        {"open": 104, "high": 106, "low": 102, "close": 105},  # c3 — low 102 > c1 high 101 ✓
    ])
    fvgs = detect_fvg(df, min_size_pips=1.0)
    assert len(fvgs) == 1
    assert fvgs[0].type == "BULLISH"
    assert fvgs[0].bottom == pytest.approx(101.0)
    assert fvgs[0].top == pytest.approx(102.0)


def test_bearish_fvg_detected():
    df = _make_df([
        {"open": 105, "high": 106, "low": 104, "close": 105},  # c1
        {"open": 104, "high": 104, "low": 100, "close": 101},  # c2 impulse down
        {"open": 101, "high": 103, "low": 100, "close": 100},  # c3 — high 103 < c1 low 104 ✓
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

from indicators.structure import find_swings, determine_bias


def _trending_up_df(n: int = 30) -> pd.DataFrame:
    rows = []
    base = 1800.0
    for i in range(n):
        o = base + i * 2
        rows.append({"open": o, "high": o + 3, "low": o - 1, "close": o + 2})
    return _make_df(rows)


def _trending_down_df(n: int = 30) -> pd.DataFrame:
    rows = []
    base = 1900.0
    for i in range(n):
        o = base - i * 2
        rows.append({"open": o, "high": o + 1, "low": o - 3, "close": o - 2})
    return _make_df(rows)


def test_bullish_bias_detected():
    df = _trending_up_df()
    swings = find_swings(df, lookback=3)
    bias = determine_bias(swings)
    assert bias == "BULLISH"


def test_bearish_bias_detected():
    df = _trending_down_df()
    swings = find_swings(df, lookback=3)
    bias = determine_bias(swings)
    assert bias == "BEARISH"


# ── Fibonacci tests ────────────────────────────────────────────────────────────

from indicators.fibonacci import FibLevels, compute_fib_from_sweep


def test_ote_zone_bullish():
    fib = compute_fib_from_sweep(sweep_low=1800.0, swing_high=1900.0)
    # OTE 0.618–0.786 retracement from high → 1900 - 100*0.618 = 1838.2
    assert fib.is_in_ote(1840.0)
    assert not fib.is_in_ote(1870.0)   # above OTE (too shallow retracement)
    assert not fib.is_in_ote(1810.0)   # below OTE (too deep)


def test_equilibrium():
    fib = FibLevels(swing_high=2000, swing_low=1800, direction="BULLISH")
    assert fib.equilibrium == pytest.approx(1900.0)


# ── Killzone tests ─────────────────────────────────────────────────────────────

from strategy.killzone import get_active_killzone
import pytz


def test_ny_am_killzone():
    dt = datetime(2024, 1, 15, 14, 30, tzinfo=pytz.utc)  # 14:30 UTC = NY AM
    kz = get_active_killzone(dt)
    assert kz == "NY_AM"


def test_london_killzone():
    dt = datetime(2024, 1, 15, 8, 0, tzinfo=pytz.utc)   # 08:00 UTC = London
    kz = get_active_killzone(dt)
    assert kz == "LONDON"


def test_outside_killzone():
    dt = datetime(2024, 1, 15, 11, 30, tzinfo=pytz.utc)  # 11:30 UTC = dead zone
    kz = get_active_killzone(dt)
    assert kz is None


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
