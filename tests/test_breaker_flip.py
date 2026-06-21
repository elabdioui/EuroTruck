import sys
from pathlib import Path

import pandas as pd
import pytest


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "detector"))

from config import cfg
from strategy import all_setups
from strategy.breaker_flip import NAME, PATTERN, scan


def _frame(periods, freq, price):
    index = pd.date_range("2026-01-15", periods=periods, freq=freq, tz="UTC")
    return pd.DataFrame({
        "open": price,
        "high": price + 0.0002,
        "low": price - 0.0002,
        "close": price,
        "volume": 100,
    }, index=index)


def _set_candle(frame, position, open_price, close, high, low):
    values = {"open": open_price, "close": close, "high": high, "low": low}
    for column, value in values.items():
        frame.iloc[position, frame.columns.get_loc(column)] = value


def valid_tf_data(direction="long", formation_index=70, broken=True, retest=True):
    m5 = _frame(100, "5min", 1.1005)
    if direction == "long":
        # Bullish candle followed by bearish displacement => bearish OB.
        _set_candle(m5, formation_index, 1.1000, 1.1010, 1.1011, 1.0999)
        _set_candle(m5, formation_index + 1, 1.1005, 1.1005, 1.1007, 1.0985)
        if broken:
            _set_candle(m5, 80, 1.1005, 1.1020, 1.1021, 1.1003)
    else:
        # Bearish candle followed by bullish displacement => bullish OB.
        _set_candle(m5, formation_index, 1.1010, 1.1000, 1.1011, 1.0999)
        _set_candle(m5, formation_index + 1, 1.1005, 1.1005, 1.1025, 1.1003)
        if broken:
            _set_candle(m5, 80, 1.1005, 1.0990, 1.1007, 1.0989)
    if not retest:
        m5.iloc[-1, m5.columns.get_loc("close")] = 1.1050

    h1 = _frame(30, "1h", 1.1000)
    if direction == "long":
        closes = [1.0950 + i * 0.0002 for i in range(30)]
    else:
        closes = [1.1050 - i * 0.0002 for i in range(30)]
    h1["close"] = closes
    return {"M5": m5, "H1": h1}


@pytest.fixture(autouse=True)
def setup_config(monkeypatch):
    monkeypatch.setattr(cfg, "PIP", 0.0001)
    monkeypatch.setattr(cfg, "OB_LOOKBACK", 30)
    monkeypatch.setattr(cfg, "SL_BUFFER_PIPS", 3.0)
    monkeypatch.setattr(cfg, "BREAKER_LOOKBACK_M5", 50)
    monkeypatch.setattr(cfg, "BREAKER_RETEST_TOLERANCE_PIPS", 1.0)
    monkeypatch.setattr(cfg, "BREAKER_MIN_RISK_PIPS", 5.0)
    monkeypatch.setattr(cfg, "BREAKER_REQUIRE_H1_BIAS_ALIGN", False)


def test_setup_registered():
    spec = next(item for item in all_setups() if item.name == NAME)
    assert spec.killzone_mode == "preferred"
    assert spec.killzones == ("LONDON", "NY_AM")
    assert spec.cooldown_seconds == 3600


def test_insufficient_data_returns_none():
    assert scan({"M5": _frame(20, "5min", 1.1), "H1": _frame(20, "1h", 1.1)}) is None


def test_no_ob_in_lookback_returns_none():
    assert scan(valid_tf_data(formation_index=40)) is None


def test_ob_not_broken_returns_none():
    assert scan(valid_tf_data(broken=False)) is None


def test_ob_wick_pierce_without_close_is_not_breaker():
    data = valid_tf_data("long", broken=False)
    data["M5"].iloc[80, data["M5"].columns.get_loc("high")] = 1.1020
    assert scan(data) is None


def test_long_breaker_full_pipeline():
    signal = scan(valid_tf_data("long"))
    assert signal is not None
    assert signal["direction"] == "long"
    assert signal["sl"] < signal["entry"] < signal["tp1"] < signal["tp_final"]
    assert signal["tp_final"] - signal["entry"] == pytest.approx(
        2 * (signal["entry"] - signal["sl"])
    )


def test_short_breaker_full_pipeline():
    signal = scan(valid_tf_data("short"))
    assert signal is not None
    assert signal["direction"] == "short"
    assert signal["tp_final"] < signal["tp1"] < signal["entry"] < signal["sl"]
    assert signal["entry"] - signal["tp_final"] == pytest.approx(
        2 * (signal["sl"] - signal["entry"])
    )


def test_not_retesting_now_returns_none():
    data = valid_tf_data()
    data["M5"].iloc[-2, data["M5"].columns.get_loc("close")] = 1.1050
    assert scan(data) is None


def test_forming_candle_does_not_change_signal():
    data = valid_tf_data("long")
    expected = scan(data)
    _set_candle(data["M5"], -1, 1.2000, 1.2000, 1.3000, 0.9000)
    actual = scan(data)
    assert actual is not None and expected is not None
    assert actual["entry"] == expected["entry"]


def test_h1_bias_filter_applied_when_enabled(monkeypatch):
    data = valid_tf_data("long")
    data["H1"]["close"] = list(reversed(data["H1"]["close"].tolist()))
    monkeypatch.setattr(cfg, "BREAKER_REQUIRE_H1_BIAS_ALIGN", True)
    assert scan(data) is None


def test_h1_bias_tag_when_disabled():
    data = valid_tf_data("long")
    data["H1"]["close"] = list(reversed(data["H1"]["close"].tolist()))
    signal = scan(data)
    assert signal is not None
    assert signal["meta"]["h_bias_aligned"] is False


def test_risk_below_minimum_returns_none(monkeypatch):
    monkeypatch.setattr(cfg, "BREAKER_MIN_RISK_PIPS", 100.0)
    assert scan(valid_tf_data()) is None


def test_signal_payload_has_required_fields():
    signal = scan(valid_tf_data())
    assert signal is not None
    assert {"direction", "pattern", "entry", "sl", "tp1", "tp_final", "meta"} <= signal.keys()
    assert signal["pattern"] == PATTERN
    assert {"ob_top", "ob_bottom", "broken_at_index"} <= set(signal["meta"])
    assert signal["meta"]["fvg_ob_confluence"] is True
    assert all(isinstance(signal["meta"][key], bool) for key in (
        "h_bias_aligned", "fvg_ob_confluence", "liquidity_confluence"
    ))
