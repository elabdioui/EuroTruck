import sys
from pathlib import Path

import pandas as pd
import pytest


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "detector"))

from config import cfg
from strategy import all_setups
from strategy.silver_bullet import NAME, PATTERN, scan


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


def _m5(direction="long", end="2026-01-15 15:30", mitigated=True, fvg=True):
    frame = _frame(100, "5min", end, 1.1005)
    if fvg and direction == "long":
        _set_candle(frame, 94, 1.0999, 1.0999, 1.1000, 1.0997)
        _set_candle(frame, 95, 1.1000, 1.1012, 1.1014, 1.0999)
        _set_candle(frame, 96, 1.1011, 1.1013, 1.1015, 1.1010)
        _set_candle(frame, 98, 1.1006, 1.1006, 1.1011, 1.1004)
        current = 1.1005 if mitigated else 1.1016
    elif fvg:
        _set_candle(frame, 94, 1.1011, 1.1011, 1.1013, 1.1010)
        _set_candle(frame, 95, 1.1010, 1.0998, 1.1011, 1.0996)
        _set_candle(frame, 96, 1.0999, 1.0997, 1.1000, 1.0995)
        _set_candle(frame, 98, 1.1004, 1.1004, 1.1006, 1.0999)
        current = 1.1005 if mitigated else 1.0994
    else:
        current = 1.1005
    _set_candle(frame, 99, current, current, current + 0.0001, current - 0.0001)
    return frame


def _h1(end="2026-01-15 15:00"):
    return _frame(30, "1h", end, 1.1000)


def valid_tf_data(direction="long", end="2026-01-15 15:30", mitigated=True):
    return {
        "M5": _m5(direction, end=end, mitigated=mitigated),
        "H1": _h1(end),
    }


@pytest.fixture(autouse=True)
def setup_config(monkeypatch):
    monkeypatch.setattr(cfg, "PIP", 0.0001)
    monkeypatch.setattr(cfg, "FVG_MIN_SIZE_PIPS", 2.0)
    monkeypatch.setattr(cfg, "SL_BUFFER_PIPS", 3.0)
    monkeypatch.setattr(cfg, "SILVER_BULLET_NY_START_HOUR", 10)
    monkeypatch.setattr(cfg, "SILVER_BULLET_NY_END_HOUR", 11)
    monkeypatch.setattr(cfg, "SILVER_BULLET_MIN_RISK_PIPS", 4.0)


def test_setup_registered():
    spec = next(item for item in all_setups() if item.name == NAME)
    assert spec.killzone_mode == "required"
    assert spec.killzones == ("NY_AM",)
    assert spec.cooldown_seconds == 1800


def test_insufficient_data_returns_none():
    data = {
        "M5": _frame(20, "5min", "2026-01-15 15:30", 1.1000),
        "H1": _frame(5, "1h", "2026-01-15 15:00", 1.1000),
    }
    assert scan(data) is None


def test_outside_sub_window_returns_none():
    assert scan(valid_tf_data(end="2026-01-15 17:00")) is None


def test_no_fvg_in_window_returns_none():
    data = valid_tf_data()
    data["M5"] = _m5(fvg=False)
    assert scan(data) is None


def test_fvg_not_mitigated_returns_none():
    assert scan(valid_tf_data(mitigated=False)) is None


def test_long_silver_bullet_full_pipeline():
    signal = scan(valid_tf_data("long"))
    assert signal is not None
    assert signal["direction"] == "long"
    assert signal["sl"] < signal["entry"] < signal["tp1"] < signal["tp_final"]
    assert signal["tp_final"] - signal["entry"] == pytest.approx(
        2 * (signal["entry"] - signal["sl"])
    )


def test_short_silver_bullet_full_pipeline():
    signal = scan(valid_tf_data("short"))
    assert signal is not None
    assert signal["direction"] == "short"
    assert signal["tp_final"] < signal["tp1"] < signal["entry"] < signal["sl"]
    assert signal["entry"] - signal["tp_final"] == pytest.approx(
        2 * (signal["sl"] - signal["entry"])
    )


def test_dst_transition_window_correct():
    winter = scan(valid_tf_data("long", end="2026-01-15 15:30"))
    summer = scan(valid_tf_data("long", end="2026-07-15 14:30"))
    assert winter is not None
    assert summer is not None
    assert winter["meta"]["ny_hour"] == 10
    assert summer["meta"]["ny_hour"] == 10


def test_risk_below_minimum_returns_none(monkeypatch):
    monkeypatch.setattr(cfg, "SILVER_BULLET_MIN_RISK_PIPS", 100.0)
    assert scan(valid_tf_data("long")) is None


def test_signal_payload_has_required_fields():
    signal = scan(valid_tf_data("long"))
    assert signal is not None
    assert {
        "direction", "pattern", "entry", "sl", "tp1", "tp_final", "meta"
    }.issubset(signal)
    assert signal["pattern"] == PATTERN
    assert {"fvg_top", "fvg_bottom", "ny_hour", "h1_bias"} == set(signal["meta"])
