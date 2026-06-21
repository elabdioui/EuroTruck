import sys
from datetime import datetime
from pathlib import Path

import pandas as pd
import pytest
import pytz


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "detector"))

from config import Config, cfg
from strategy.killzone import get_session_window_utc
from strategy.london_judas import _find_sweep, scan
from test_london_judas import valid_tf_data


@pytest.fixture(autouse=True)
def judas_config(monkeypatch):
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


def test_sweep_requires_one_rejection_candle():
    separated = pd.DataFrame({
        "high": [1.1040, 1.1040, 1.1040],
        "low": [1.0995, 1.0998, 1.1002],
        "close": [1.0998, 1.0999, 1.1005],
    })
    assert _find_sweep(separated, 1.1000, 1.1050) is None

    rejected = separated.copy()
    rejected.loc[1, ["low", "close"]] = [1.0995, 1.1002]
    assert _find_sweep(rejected, 1.1000, 1.1050) == ("long", 1, 1.0995)


def test_h4_bias_rejects_countertrend_sweep():
    data = valid_tf_data("long")
    closes = data["H4"].columns.get_loc("close")
    for position in range(len(data["H4"]) - 1):
        data["H4"].iloc[position, closes] = 1.1200 - position * 0.0005
    assert scan(data) is None


def test_h4_bias_allows_aligned_sweep():
    assert scan(valid_tf_data("long")) is not None


def test_fvg_or_ob_is_required_in_ote(monkeypatch):
    monkeypatch.setattr(cfg, "FVG_MIN_SIZE_PIPS", 10_000.0)
    monkeypatch.setattr(Config, "OB_MIN_BODY_PIPS", 10_000.0)
    assert scan(valid_tf_data("long")) is None


def test_overlapping_fvg_allows_signal_and_sl_clears_sweep():
    signal = scan(valid_tf_data("long"))
    assert signal is not None
    assert signal["meta"]["ote_confluence"] == "FVG"
    assert signal["sl"] < signal["meta"]["sweep_extreme"]


def test_require_flags_can_be_disabled(monkeypatch):
    data = valid_tf_data("long")
    closes = data["H4"].columns.get_loc("close")
    for position in range(len(data["H4"]) - 1):
        data["H4"].iloc[position, closes] = 1.1200 - position * 0.0005
    monkeypatch.setattr(cfg, "LONDON_JUDAS_REQUIRE_H4_BIAS", False)
    monkeypatch.setattr(cfg, "LONDON_JUDAS_REQUIRE_FVG_OB", False)
    monkeypatch.setattr(cfg, "FVG_MIN_SIZE_PIPS", 10_000.0)
    monkeypatch.setattr(Config, "OB_MIN_BODY_PIPS", 10_000.0)
    assert scan(data) is not None


def test_forming_m5_candle_is_ignored():
    data = valid_tf_data("long")
    expected_entry = float(data["M5"].iloc[-2]["close"])
    data["M5"].iloc[-1, data["M5"].columns.get_loc("close")] = 0.5
    data["M5"].iloc[-1, data["M5"].columns.get_loc("low")] = 0.4
    signal = scan(data)
    assert signal is not None
    assert signal["entry"] == expected_entry


def test_signal_has_all_required_strategy_fields():
    signal = scan(valid_tf_data("long"))
    assert signal is not None
    assert all(signal[field] is not None for field in (
        "direction", "pattern", "entry", "sl", "tp1", "tp_final", "meta"
    ))
    assert signal["meta"]["ote_confluence"] is not None


@pytest.mark.parametrize(
    ("reference", "expected_start", "expected_end"),
    [
        (datetime(2026, 1, 15, 8, tzinfo=pytz.utc), 1, 5),
        (datetime(2026, 7, 15, 8, tzinfo=pytz.utc), 0, 4),
    ],
)
def test_asia_window_tracks_new_york_dst(reference, expected_start, expected_end):
    start, end = get_session_window_utc("ASIA", reference)
    assert start.hour == expected_start
    assert end.hour == expected_end
