import sys
from pathlib import Path

import pandas as pd
import pytest


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "detector"))

from config import cfg
from strategy import all_setups
from strategy.overlap_bos import NAME, PATTERN, scan


def _frame(periods, freq, end, price):
    index = pd.date_range(end=end, periods=periods, freq=freq, tz="UTC")
    return pd.DataFrame({
        "open": price,
        "high": price + 0.0002,
        "low": price - 0.0002,
        "close": price,
        "volume": 100,
    }, index=index)


def _set_candle(frame, position, open_price, close, high, low):
    frame.iloc[position, frame.columns.get_loc("open")] = open_price
    frame.iloc[position, frame.columns.get_loc("close")] = close
    frame.iloc[position, frame.columns.get_loc("high")] = high
    frame.iloc[position, frame.columns.get_loc("low")] = low


def _m15(direction="long", end="2026-01-15 13:30", bos=True):
    base = 1.1010 if direction == "long" else 1.1090
    frame = _frame(100, "15min", end, base)
    if not bos:
        return frame
    if direction == "long":
        _set_candle(frame, 90, 1.1005, 1.1005, 1.1010, 1.1000)
        _set_candle(frame, 93, 1.1015, 1.1018, 1.1020, 1.1012)
        _set_candle(frame, 97, 1.1011, 1.1025, 1.1040, 1.1010)
    else:
        _set_candle(frame, 90, 1.1095, 1.1095, 1.1100, 1.1090)
        _set_candle(frame, 93, 1.1085, 1.1082, 1.1088, 1.1080)
        _set_candle(frame, 97, 1.1089, 1.1075, 1.1090, 1.1060)
    return frame


def _m5(direction="long", end="2026-01-15 13:30", entry=None):
    default = 1.1014 if direction == "long" else 1.1086
    current = default if entry is None else entry
    return _frame(100, "5min", end, current)


def valid_tf_data(direction="long", end="2026-01-15 13:30", entry=None):
    return {
        "M15": _m15(direction, end=end),
        "M5": _m5(direction, end=end, entry=entry),
    }


@pytest.fixture(autouse=True)
def setup_config(monkeypatch):
    monkeypatch.setattr(cfg, "PIP", 0.0001)
    monkeypatch.setattr(cfg, "SWING_LOOKBACK", 2)
    monkeypatch.setattr(cfg, "OTE_ENTRY_TOLERANCE_PIPS", 1.0)
    monkeypatch.setattr(cfg, "SL_BUFFER_PIPS", 3.0)
    monkeypatch.setattr(cfg, "OVERLAP_BOS_NY_START_HOUR", 8)
    monkeypatch.setattr(cfg, "OVERLAP_BOS_NY_END_HOUR", 10)
    monkeypatch.setattr(cfg, "OVERLAP_BOS_FIB_LOW", 0.5)
    monkeypatch.setattr(cfg, "OVERLAP_BOS_FIB_HIGH", 0.79)
    monkeypatch.setattr(cfg, "OVERLAP_BOS_MIN_RISK_PIPS", 6.0)


def test_setup_registered():
    spec = next(item for item in all_setups() if item.name == NAME)
    assert spec.killzone_mode == "required"
    assert spec.killzones == ("NY_AM",)
    assert spec.cooldown_seconds == 2400


def test_insufficient_data_returns_none():
    data = {
        "M15": _frame(20, "15min", "2026-01-15 13:30", 1.1000),
        "M5": _frame(20, "5min", "2026-01-15 13:30", 1.1000),
    }
    assert scan(data) is None


def test_outside_sub_window_returns_none():
    assert scan(valid_tf_data(end="2026-01-15 15:00")) is None


def test_no_m15_bos_returns_none():
    data = valid_tf_data()
    data["M15"] = _m15("long", bos=False)
    assert scan(data) is None


def test_long_overlap_bos_full_pipeline():
    signal = scan(valid_tf_data("long"))
    assert signal is not None
    assert signal["direction"] == "long"
    assert signal["sl"] < signal["entry"] < signal["tp1"] < signal["tp_final"]
    assert signal["tp_final"] - signal["entry"] == pytest.approx(
        2 * (signal["entry"] - signal["sl"])
    )


def test_short_overlap_bos_full_pipeline():
    signal = scan(valid_tf_data("short"))
    assert signal is not None
    assert signal["direction"] == "short"
    assert signal["tp_final"] < signal["tp1"] < signal["entry"] < signal["sl"]
    assert signal["entry"] - signal["tp_final"] == pytest.approx(
        2 * (signal["sl"] - signal["entry"])
    )


def test_pullback_outside_fib_zone_returns_none():
    assert scan(valid_tf_data("long", entry=1.1035)) is None


def test_dst_transition_sub_window_correct():
    winter = scan(valid_tf_data("long", end="2026-01-15 13:30"))
    summer = scan(valid_tf_data("long", end="2026-07-15 12:30"))
    assert winter is not None
    assert summer is not None
    assert winter["meta"]["ny_hour"] == 8
    assert summer["meta"]["ny_hour"] == 8


def test_risk_below_minimum_returns_none(monkeypatch):
    monkeypatch.setattr(cfg, "OVERLAP_BOS_MIN_RISK_PIPS", 100.0)
    assert scan(valid_tf_data("long")) is None


def test_signal_payload_has_required_fields():
    signal = scan(valid_tf_data("long"))
    assert signal is not None
    assert {
        "direction", "pattern", "entry", "sl", "tp1", "tp_final", "meta"
    }.issubset(signal)
    assert signal["pattern"] == PATTERN
    assert {
        "m15_bos_anchor", "displacement_extreme", "ny_hour"
    } == set(signal["meta"])
