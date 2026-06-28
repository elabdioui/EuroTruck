import sys
from pathlib import Path

import pandas as pd
import pytest


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "detector"))

from config import cfg
from strategy import all_setups
from strategy.pdh_pdl_sweep import NAME, PATTERN, scan


def _frame(periods, freq, end, price):
    index = pd.date_range(end=end, periods=periods, freq=freq, tz="UTC")
    return pd.DataFrame({
        "open": price,
        "high": price + 0.0001,
        "low": price - 0.0001,
        "close": price,
        "volume": 100,
    }, index=index)


def _d1():
    frame = _frame(5, "1D", "2026-01-15", 1.1050)
    frame.iloc[-2, frame.columns.get_loc("high")] = 1.1100
    frame.iloc[-2, frame.columns.get_loc("low")] = 1.1000
    return frame


def _set_candle(frame, position, open_price, close, high, low):
    frame.iloc[position, frame.columns.get_loc("open")] = open_price
    frame.iloc[position, frame.columns.get_loc("close")] = close
    frame.iloc[position, frame.columns.get_loc("high")] = high
    frame.iloc[position, frame.columns.get_loc("low")] = low


def _m5(direction, entry=None, bos=True, rejection="valid"):
    base = 1.1007 if direction == "long" else 1.1093
    frame = _frame(100, "5min", "2026-01-15 08:15", base)

    if direction == "long":
        sweep_open, sweep_close = 1.1003, 1.1002
        if rejection == "wrong_close":
            sweep_open, sweep_close = 1.1001, 1.0998
        elif rejection == "thick_body":
            sweep_open, sweep_close = 1.0996, 1.1002
        _set_candle(frame, 86, sweep_open, sweep_close, 1.1005, 1.0995)
        if bos:
            _set_candle(frame, 89, 1.1015, 1.1018, 1.1020, 1.1014)
            _set_candle(frame, 93, 1.1008, 1.1025, 1.1035, 1.1007)
        final = 1.1007 if entry is None else entry
    else:
        sweep_open, sweep_close = 1.1097, 1.1098
        if rejection == "wrong_close":
            sweep_open, sweep_close = 1.1099, 1.1102
        elif rejection == "thick_body":
            sweep_open, sweep_close = 1.1104, 1.1098
        _set_candle(frame, 86, sweep_open, sweep_close, 1.1105, 1.1095)
        if bos:
            _set_candle(frame, 89, 1.1085, 1.1082, 1.1086, 1.1080)
            _set_candle(frame, 93, 1.1092, 1.1075, 1.1093, 1.1065)
        final = 1.1093 if entry is None else entry

    _set_candle(frame, 99, final, final, final + 0.0001, final - 0.0001)
    return frame


def valid_tf_data(direction="long", entry=None):
    return {"D1": _d1(), "M5": _m5(direction, entry=entry)}


@pytest.fixture(autouse=True)
def setup_config(monkeypatch):
    monkeypatch.setattr(cfg, "PIP", 0.0001)
    monkeypatch.setattr(cfg, "SWING_LOOKBACK", 2)
    monkeypatch.setattr(cfg, "OTE_LOW", 0.618)
    monkeypatch.setattr(cfg, "OTE_HIGH", 0.786)
    monkeypatch.setattr(cfg, "OTE_ENTRY_TOLERANCE_PIPS", 1.0)
    monkeypatch.setattr(cfg, "PDH_PDL_LOOKBACK_M5", 24)
    monkeypatch.setattr(cfg, "PDH_PDL_WICK_BODY_RATIO_MAX", 0.5)
    monkeypatch.setattr(cfg, "PDH_PDL_MIN_RISK_PIPS", 5.0)
    monkeypatch.setattr(cfg, "SL_BUFFER_PIPS", 3.0)


def test_setup_registered():
    spec = next(item for item in all_setups() if item.name == NAME)
    assert spec.killzone_mode == "required"
    assert spec.killzones == ("LONDON", "NY_AM", "NY_PM")
    assert spec.cooldown_seconds == 3600


def test_insufficient_data_returns_none():
    data = {
        "D1": _frame(2, "1D", "2026-01-15", 1.1050),
        "M5": _frame(20, "5min", "2026-01-15 08:15", 1.1050),
    }
    assert scan(data) is None


def test_no_sweep_returns_none():
    data = valid_tf_data()
    data["M5"] = _frame(100, "5min", "2026-01-15 08:15", 1.1050)
    assert scan(data) is None


def test_sweep_without_rejection_close_returns_none():
    data = valid_tf_data()
    data["M5"] = _m5("long", rejection="wrong_close")
    assert scan(data) is None


def test_sweep_with_thick_body_returns_none():
    data = valid_tf_data()
    data["M5"] = _m5("long", rejection="thick_body")
    assert scan(data) is None


def test_long_pdl_sweep_full_pipeline():
    signal = scan(valid_tf_data("long"))
    assert signal is not None
    assert signal["direction"] == "long"
    assert signal["sl"] < signal["entry"] < signal["tp1"] < signal["tp_final"]
    assert signal["tp_final"] - signal["entry"] == pytest.approx(
        2 * (signal["entry"] - signal["sl"])
    )


def test_short_pdh_sweep_full_pipeline():
    signal = scan(valid_tf_data("short"))
    assert signal is not None
    assert signal["direction"] == "short"
    assert signal["tp_final"] < signal["tp1"] < signal["entry"] < signal["sl"]
    assert signal["entry"] - signal["tp_final"] == pytest.approx(
        2 * (signal["sl"] - signal["entry"])
    )


def test_no_reversal_bos_returns_none():
    data = valid_tf_data("long")
    data["M5"] = _m5("long", bos=False)
    assert scan(data) is None


def test_outside_entry_zone_returns_none():
    data = valid_tf_data("long")
    _set_candle(data["M5"], -2, 1.1020, 1.1020, 1.1021, 1.1019)
    assert scan(data) is None


def test_forming_candle_does_not_change_signal():
    data = valid_tf_data("long")
    expected = scan(data)
    _set_candle(data["M5"], -1, 1.2000, 1.2000, 1.3000, 0.9000)
    actual = scan(data)
    assert actual is not None and expected is not None
    assert actual["entry"] == expected["entry"]


def test_risk_below_minimum_returns_none(monkeypatch):
    monkeypatch.setattr(cfg, "PDH_PDL_MIN_RISK_PIPS", 100.0)
    assert scan(valid_tf_data("long")) is None


def test_counter_bias_is_tagged_not_gated_by_default():
    signal = scan(valid_tf_data("long"))
    assert signal is not None
    assert signal["meta"]["h_bias_aligned"] is False


def test_optional_bias_gate(monkeypatch):
    monkeypatch.setattr(cfg, "PDH_PDL_REQUIRE_BIAS", True)
    assert scan(valid_tf_data("long")) is None


def test_signal_payload_has_required_fields():
    signal = scan(valid_tf_data("long"))
    assert signal is not None
    assert {
        "direction", "pattern", "entry", "sl", "tp1", "tp_final", "meta"
    }.issubset(signal)
    assert signal["pattern"] == PATTERN
    assert {"pdh", "pdl", "sweep_wick"} <= set(signal["meta"])
    assert all(isinstance(signal["meta"][key], bool) for key in (
        "h_bias_aligned", "fvg_ob_confluence", "liquidity_confluence"
    ))
