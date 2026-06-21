import sys
from pathlib import Path

import pandas as pd


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "detector"))

from config import cfg
from indicators.liquidity import (
    find_equal_highs_lows,
    find_recent_liquidity_sweep,
    find_swing_liquidity,
)
from strategy.ict_tags import build_ict_tags


TAG_KEYS = {
    "h_bias_aligned",
    "fvg_ob_confluence",
    "liquidity_confluence",
}


def _frame(periods=40, price=1.1000):
    index = pd.date_range("2026-01-15", periods=periods, freq="5min", tz="UTC")
    return pd.DataFrame({
        "open": price,
        "high": price + 0.0002,
        "low": price - 0.0002,
        "close": price,
    }, index=index)


def test_equal_highs_lows_and_swing_liquidity_use_closed_bars(monkeypatch):
    monkeypatch.setattr(cfg, "PIP", 0.0001)
    monkeypatch.setattr(cfg, "LIQUIDITY_EQUAL_TOLERANCE_PIPS", 1.0)
    monkeypatch.setattr(cfg, "SWING_LOOKBACK", 2)
    frame = _frame()
    frame.iloc[10, frame.columns.get_loc("high")] = 1.1010
    frame.iloc[11, frame.columns.get_loc("high")] = 1.1010
    frame.iloc[20, frame.columns.get_loc("low")] = 1.0990
    frame.iloc[-1, frame.columns.get_loc("high")] = 2.0

    equals = find_equal_highs_lows(frame)
    swings = find_swing_liquidity(frame)
    assert any(level.type == "BSL" and level.price == 1.1010 for level in equals)
    assert all(level.price != 2.0 for level in equals + swings)


def test_recent_ssl_sweep_is_tagged_for_long(monkeypatch):
    monkeypatch.setattr(cfg, "PIP", 0.0001)
    monkeypatch.setattr(cfg, "LIQUIDITY_EQUAL_TOLERANCE_PIPS", 1.0)
    monkeypatch.setattr(cfg, "LIQUIDITY_SWEEP_LOOKBACK_M5", 30)
    monkeypatch.setattr(cfg, "SWING_LOOKBACK", 2)
    frame = _frame()
    frame.iloc[20, frame.columns.get_loc("low")] = 1.0990
    frame.iloc[21, frame.columns.get_loc("low")] = 1.0990
    frame.iloc[30, frame.columns.get_loc("low")] = 1.0988
    frame.iloc[30, frame.columns.get_loc("close")] = 1.0992
    sweep = find_recent_liquidity_sweep(frame, "long")
    assert sweep is not None
    assert sweep.type == "SSL"


def test_uniform_tag_builder_returns_three_booleans(monkeypatch):
    monkeypatch.setattr(cfg, "PIP", 0.0001)
    monkeypatch.setattr(cfg, "LIQUIDITY_EQUAL_TOLERANCE_PIPS", 1.0)
    monkeypatch.setattr(cfg, "LIQUIDITY_SWEEP_LOOKBACK_M5", 30)
    monkeypatch.setattr(cfg, "SWING_LOOKBACK", 2)
    tags = build_ict_tags(
        {"M5": _frame()}, "long", 1.0990, 1.1000, forced_fvg_ob=False
    )
    assert TAG_KEYS <= tags.keys()
    assert all(isinstance(tags[key], bool) for key in TAG_KEYS)
