import sys
from pathlib import Path

import pandas as pd
import pytest


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "detector"))

from config import cfg
from strategy import all_setups
from strategy.ote_continuation import NAME, PATTERN, scan


def _frame(periods, freq, end, price):
    index = pd.date_range(end=end, periods=periods, freq=freq, tz="UTC")
    return pd.DataFrame({
        "open": price,
        "high": price + 0.0001,
        "low": price - 0.0001,
        "close": price,
        "volume": 100,
    }, index=index)


def _h4(direction):
    frame = _frame(30, "4h", "2026-01-15 08:00", 1.1000)
    step = 0.0005 if direction == "long" else -0.0005
    closes = [1.1000 + step * position for position in range(len(frame))]
    frame["open"] = closes
    frame["close"] = closes
    frame["high"] = frame["close"] + 0.0002
    frame["low"] = frame["close"] - 0.0002
    return frame


def _m15(direction, small=False):
    frame = _frame(96, "15min", "2026-01-15 08:15", 1.1020)
    size = 0.0010 if small else 0.0040
    if direction == "long":
        closes = [1.1001 + size * position / 23 for position in range(24)]
        lows = [value - 0.0001 for value in closes]
        highs = [value + 0.0001 for value in closes]
        lows[0] = 1.1000
        highs[-1] = 1.1000 + size
    else:
        closes = [1.1039 - size * position / 23 for position in range(24)]
        lows = [value - 0.0001 for value in closes]
        highs = [value + 0.0001 for value in closes]
        highs[0] = 1.1040
        lows[-1] = 1.1040 - size
    frame.iloc[-24:, frame.columns.get_loc("open")] = closes
    frame.iloc[-24:, frame.columns.get_loc("close")] = closes
    frame.iloc[-24:, frame.columns.get_loc("high")] = highs
    frame.iloc[-24:, frame.columns.get_loc("low")] = lows
    return frame


def _set_candle(frame, position, close, high, low):
    frame.iloc[position, frame.columns.get_loc("open")] = close
    frame.iloc[position, frame.columns.get_loc("close")] = close
    frame.iloc[position, frame.columns.get_loc("high")] = high
    frame.iloc[position, frame.columns.get_loc("low")] = low


def _m5(direction, entry=None, bos=True):
    if direction == "long":
        final = 1.1012 if entry is None else entry
        frame = _frame(100, "5min", "2026-01-15 08:15", 1.1007)
        if bos:
            _set_candle(frame, 90, 1.1008, 1.1010, 1.1006)
            _set_candle(frame, 93, 1.1012, 1.1013, 1.1009)
            for position in range(94, 99):
                _set_candle(frame, position, 1.1011, 1.1012, 1.1010)
    else:
        final = 1.1028 if entry is None else entry
        frame = _frame(100, "5min", "2026-01-15 08:15", 1.1033)
        if bos:
            _set_candle(frame, 90, 1.1032, 1.1034, 1.1030)
            _set_candle(frame, 93, 1.1028, 1.1031, 1.1027)
            for position in range(94, 99):
                _set_candle(frame, position, 1.1029, 1.1030, 1.1028)
    _set_candle(frame, 99, final, final + 0.0001, final - 0.0001)
    return frame


def valid_tf_data(direction="long", entry=None):
    return {
        "M5": _m5(direction, entry=entry),
        "M15": _m15(direction),
        "H4": _h4(direction),
    }


@pytest.fixture(autouse=True)
def setup_config(monkeypatch):
    monkeypatch.setattr(cfg, "PIP", 0.0001)
    monkeypatch.setattr(cfg, "SWING_LOOKBACK", 2)
    monkeypatch.setattr(cfg, "OTE_LOW", 0.618)
    monkeypatch.setattr(cfg, "OTE_HIGH", 0.786)
    monkeypatch.setattr(cfg, "OTE_ENTRY_TOLERANCE_PIPS", 1.0)
    monkeypatch.setattr(cfg, "OTE_CONT_MIN_IMPULSE_PIPS", 25.0)
    monkeypatch.setattr(cfg, "OTE_CONT_MIN_RISK_PIPS", 5.0)
    monkeypatch.setattr(cfg, "OTE_CONT_BIAS_EMA", 20)
    monkeypatch.setattr(cfg, "SL_BUFFER_PIPS", 3.0)


def test_setup_registered():
    spec = next(item for item in all_setups() if item.name == NAME)
    assert spec.killzone_mode == "required"
    assert spec.killzones == ("LONDON", "NY_AM", "NY_PM")
    assert spec.cooldown_seconds == 2400


def test_insufficient_data_returns_none():
    data = {
        "M5": _frame(20, "5min", "2026-01-15 08:15", 1.1000),
        "M15": _frame(20, "15min", "2026-01-15 08:15", 1.1000),
        "H4": _frame(5, "4h", "2026-01-15 08:00", 1.1000),
    }
    assert scan(data) is None


def test_unclear_h4_bias_returns_none():
    data = valid_tf_data()
    data["H4"] = _frame(30, "4h", "2026-01-15 08:00", 1.1000)
    assert scan(data) is None


def test_impulse_too_small_returns_none():
    data = valid_tf_data()
    data["M15"] = _m15("long", small=True)
    assert scan(data) is None


def test_long_ote_continuation_full_pipeline():
    signal = scan(valid_tf_data("long"))
    assert signal is not None
    assert signal["direction"] == "long"
    assert signal["sl"] < signal["entry"] < signal["tp1"] < signal["tp_final"]
    assert signal["tp_final"] - signal["entry"] == pytest.approx(
        2 * (signal["entry"] - signal["sl"])
    )


def test_short_ote_continuation_full_pipeline():
    signal = scan(valid_tf_data("short"))
    assert signal is not None
    assert signal["direction"] == "short"
    assert signal["tp_final"] < signal["tp1"] < signal["entry"] < signal["sl"]
    assert signal["entry"] - signal["tp_final"] == pytest.approx(
        2 * (signal["sl"] - signal["entry"])
    )


def test_price_outside_ote_returns_none():
    data = valid_tf_data("long")
    _set_candle(data["M5"], -2, 1.1035, 1.1036, 1.1034)
    assert scan(data) is None


def test_forming_candle_does_not_change_signal():
    data = valid_tf_data("long")
    expected = scan(data)
    _set_candle(data["M5"], -1, 1.2000, 1.3000, 0.9000)
    actual = scan(data)
    assert actual is not None and expected is not None
    assert actual["entry"] == expected["entry"]


def test_no_continuation_bos_returns_none():
    data = valid_tf_data("long")
    data["M5"] = _m5("long", bos=False)
    assert scan(data) is None


def test_risk_below_minimum_returns_none(monkeypatch):
    monkeypatch.setattr(cfg, "OTE_CONT_MIN_RISK_PIPS", 100.0)
    assert scan(valid_tf_data("long")) is None


def test_missing_confluence_is_tagged_by_default():
    signal = scan(valid_tf_data("long"))
    assert signal is not None
    assert signal["meta"]["fvg_ob_confluence"] is False


def test_optional_confluence_gate(monkeypatch):
    monkeypatch.setattr(cfg, "OTE_CONT_REQUIRE_FVG_OB", True)
    assert scan(valid_tf_data("long")) is None


def test_signal_payload_has_required_fields():
    signal = scan(valid_tf_data("long"))
    assert signal is not None
    assert {
        "direction", "pattern", "entry", "sl", "tp1", "tp_final", "meta"
    }.issubset(signal)
    assert signal["pattern"] == PATTERN
    assert {"h4_ema", "impulse_low", "impulse_high"} <= set(signal["meta"])
    assert signal["meta"]["h_bias_aligned"] is True
    assert all(isinstance(signal["meta"][key], bool) for key in (
        "h_bias_aligned", "fvg_ob_confluence", "liquidity_confluence"
    ))
