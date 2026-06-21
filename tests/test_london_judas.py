import sys
from pathlib import Path

import pandas as pd
import pytest


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "detector"))

from config import cfg
from strategy import all_setups
from strategy.london_judas import NAME, scan


def _base_frame(periods, freq, end, price=1.1025):
    index = pd.date_range(end=end, periods=periods, freq=freq, tz="UTC")
    return pd.DataFrame({
        "open": price,
        "high": price + 0.0002,
        "low": price - 0.0002,
        "close": price,
        "volume": 100,
    }, index=index)


def _asia_frame(tight=False):
    frame = _base_frame(96, "15min", "2026-01-15 08:15", price=1.1025)
    asia_mask = (frame.index.hour >= 0) & (frame.index.hour < 6)
    if tight:
        frame.loc[asia_mask, "high"] = 1.1005
        frame.loc[asia_mask, "low"] = 1.1000
        frame.loc[asia_mask, ["open", "close"]] = 1.10025
    else:
        frame.loc[asia_mask, "high"] = 1.1050
        frame.loc[asia_mask, "low"] = 1.1000
        frame.loc[asia_mask, ["open", "close"]] = 1.1025
    return frame


def _set_candle(frame, position, close, high, low):
    frame.iloc[position, frame.columns.get_loc("open")] = close
    frame.iloc[position, frame.columns.get_loc("close")] = close
    frame.iloc[position, frame.columns.get_loc("high")] = high
    frame.iloc[position, frame.columns.get_loc("low")] = low


def _long_m5(final_close=1.1008):
    frame = _base_frame(100, "5min", "2026-01-15 08:15", price=1.1015)

    for position, close in enumerate(
        [1.1010, 1.1013, 1.1016, 1.1019, 1.1022], start=77
    ):
        _set_candle(frame, position, close, close + 0.00015, close - 0.00015)
    _set_candle(frame, 82, 1.1025, 1.1028, 1.1023)
    for position, close in enumerate(
        [1.1022, 1.1019, 1.1016, 1.1013, 1.1010], start=83
    ):
        _set_candle(frame, position, close, close + 0.00015, close - 0.00015)

    _set_candle(frame, 88, 1.1002, 1.1004, 1.0995)
    for position, close in enumerate(
        [1.1005, 1.1010, 1.1015, 1.1020, 1.1025], start=89
    ):
        _set_candle(frame, position, close, close + 0.00015, close - 0.00015)
    _set_candle(frame, 94, 1.1032, 1.1035, 1.1024)
    _set_candle(frame, 95, 1.1038, 1.1040, 1.1030)
    _set_candle(frame, 96, 1.1030, 1.1032, 1.1028)
    _set_candle(frame, 97, 1.1020, 1.1022, 1.1018)
    _set_candle(frame, 98, 1.1013, 1.1015, 1.1011)
    _set_candle(frame, 99, final_close, final_close + 0.0002, final_close - 0.0002)
    return frame


def _short_m5(final_close=1.1041):
    frame = _base_frame(100, "5min", "2026-01-15 08:15", price=1.1035)

    for position, close in enumerate(
        [1.1040, 1.1037, 1.1034, 1.1031, 1.1028], start=77
    ):
        _set_candle(frame, position, close, close + 0.00015, close - 0.00015)
    _set_candle(frame, 82, 1.1025, 1.1027, 1.1022)
    for position, close in enumerate(
        [1.1028, 1.1032, 1.1036, 1.1040, 1.1044], start=83
    ):
        _set_candle(frame, position, close, close + 0.00015, close - 0.00015)

    _set_candle(frame, 88, 1.1049, 1.1055, 1.1047)
    for position, close in enumerate(
        [1.1048, 1.1043, 1.1038, 1.1033, 1.1025], start=89
    ):
        _set_candle(frame, position, close, close + 0.00015, close - 0.00015)
    _set_candle(frame, 94, 1.1018, 1.1026, 1.1015)
    _set_candle(frame, 95, 1.1012, 1.1020, 1.1010)
    _set_candle(frame, 96, 1.1020, 1.1022, 1.1018)
    _set_candle(frame, 97, 1.1030, 1.1032, 1.1028)
    _set_candle(frame, 98, 1.1037, 1.1039, 1.1035)
    _set_candle(frame, 99, final_close, final_close + 0.0002, final_close - 0.0002)
    return frame


def valid_tf_data(direction="long", final_close=None):
    if direction == "long":
        m5 = _long_m5(1.1008 if final_close is None else final_close)
    else:
        m5 = _short_m5(1.1041 if final_close is None else final_close)
    h4 = _base_frame(30, "4h", "2026-01-15 08:00", price=1.1025)
    step = 0.0005 if direction == "long" else -0.0005
    for position in range(len(h4) - 1):
        h4.iloc[position, h4.columns.get_loc("close")] = 1.1025 + position * step
    # Deliberately opposite: the forming H4 candle must not affect the bias.
    h4.iloc[-1, h4.columns.get_loc("close")] = 1.0 if direction == "long" else 1.2
    return {
        "M5": m5,
        "M15": _asia_frame(),
        "H4": h4,
    }


@pytest.fixture(autouse=True)
def setup_config(monkeypatch):
    monkeypatch.setattr(cfg, "PIP", 0.0001)
    monkeypatch.setattr(cfg, "SWING_LOOKBACK", 5)
    monkeypatch.setattr(cfg, "OTE_LOW", 0.618)
    monkeypatch.setattr(cfg, "OTE_HIGH", 0.786)
    monkeypatch.setattr(cfg, "OTE_ENTRY_TOLERANCE_PIPS", 1.0)
    monkeypatch.setattr(cfg, "LONDON_JUDAS_LOOKBACK_M5", 12)
    monkeypatch.setattr(cfg, "LONDON_JUDAS_MIN_RANGE_PIPS", 15.0)
    monkeypatch.setattr(cfg, "LONDON_JUDAS_MIN_RISK_PIPS", 5.0)
    monkeypatch.setattr(cfg, "LONDON_JUDAS_BIAS_EMA", 20)
    monkeypatch.setattr(cfg, "LONDON_JUDAS_REQUIRE_H4_BIAS", True)
    monkeypatch.setattr(cfg, "LONDON_JUDAS_REQUIRE_FVG_OB", True)
    monkeypatch.setattr(cfg, "SL_BUFFER_PIPS", 3.0)


def test_setup_registered():
    spec = next(item for item in all_setups() if item.name == NAME)
    assert spec.killzone_mode == "required"
    assert spec.killzones == ("LONDON",)
    assert spec.cooldown_seconds == 3600


def test_scan_returns_none_on_insufficient_data():
    data = {
        "M5": _base_frame(20, "5min", "2026-01-15 08:15"),
        "M15": _base_frame(20, "15min", "2026-01-15 08:15"),
        "H4": _base_frame(5, "4h", "2026-01-15 08:00"),
    }
    assert scan(data) is None


def test_scan_returns_none_on_tight_asia_range():
    data = valid_tf_data()
    data["M15"] = _asia_frame(tight=True)
    assert scan(data) is None


def test_scan_long_judas_full_pipeline():
    signal = scan(valid_tf_data("long"))
    assert signal is not None
    assert signal["direction"] == "long"
    assert signal["sl"] < signal["entry"] < signal["tp1"] < signal["tp_final"]
    assert signal["tp_final"] - signal["entry"] == pytest.approx(
        2 * (signal["entry"] - signal["sl"])
    )


def test_scan_short_judas_full_pipeline():
    signal = scan(valid_tf_data("short"))
    assert signal is not None
    assert signal["direction"] == "short"
    assert signal["tp_final"] < signal["tp1"] < signal["entry"] < signal["sl"]
    assert signal["entry"] - signal["tp_final"] == pytest.approx(
        2 * (signal["sl"] - signal["entry"])
    )


def test_scan_no_sweep_returns_none():
    data = valid_tf_data()
    data["M5"] = _base_frame(100, "5min", "2026-01-15 08:15", price=1.1025)
    assert scan(data) is None


def test_scan_sweep_without_bos_returns_none():
    data = valid_tf_data()
    flat = _base_frame(100, "5min", "2026-01-15 08:15", price=1.1025)
    _set_candle(flat, 88, 1.1002, 1.1004, 1.0995)
    _set_candle(flat, 99, 1.1005, 1.1007, 1.1003)
    data["M5"] = flat
    assert scan(data) is None


def test_scan_outside_ote_returns_none():
    data = valid_tf_data("long")
    _set_candle(data["M5"], -2, 1.1030, 1.1032, 1.1028)
    assert scan(data) is None


def test_signal_payload_has_required_fields():
    signal = scan(valid_tf_data("long"))
    assert signal is not None
    assert {
        "direction", "pattern", "entry", "sl", "tp1", "tp_final", "meta"
    }.issubset(signal)
    assert signal["meta"]
