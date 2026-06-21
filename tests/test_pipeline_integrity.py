import sys
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "detector"))
sys.path.insert(0, str(ROOT / "tests"))

from config import cfg
from strategy.breaker_flip import scan as scan_breaker
from strategy.london_judas import scan as scan_judas
from strategy.ote_continuation import scan as scan_ote
from strategy.overlap_bos import scan as scan_overlap
from strategy.pdh_pdl_sweep import scan as scan_pdh
from strategy.silver_bullet import scan as scan_silver
from test_breaker_flip import valid_tf_data as breaker_data
from test_london_judas import valid_tf_data as judas_data
from test_ote_continuation import valid_tf_data as ote_data
from test_overlap_bos import valid_tf_data as overlap_data
from test_pdh_pdl_sweep import valid_tf_data as pdh_data
from test_silver_bullet import valid_tf_data as silver_data


MAIN_SPEC = importlib.util.spec_from_file_location(
    "detector_pipeline_main", ROOT / "detector" / "main.py"
)
assert MAIN_SPEC is not None and MAIN_SPEC.loader is not None
detector_main = importlib.util.module_from_spec(MAIN_SPEC)
MAIN_SPEC.loader.exec_module(detector_main)


REQUIRED_FIELDS = {
    "setup", "direction", "pattern", "entry", "sl", "tp1", "tp_final",
    "killzone_match",
}


def _candidate():
    return {
        "direction": "long",
        "pattern": "pipeline_test",
        "entry": 1.1000,
        "sl": 1.0990,
        "tp1": 1.1010,
        "tp_final": 1.1020,
        "meta": {},
    }


def _prepare_pipeline(monkeypatch, record, send):
    spec = SimpleNamespace(
        name="dummy",
        scan=lambda _: _candidate(),
        killzone_mode="required",
        killzones=("LONDON",),
    )
    monkeypatch.setattr(detector_main, "get_active_killzone", lambda _: "LONDON")
    monkeypatch.setattr(detector_main, "runnable_setups", lambda _: [spec])
    monkeypatch.setattr(detector_main.mt5, "is_connected", lambda: True)
    monkeypatch.setattr(
        detector_main.mt5,
        "get_all_timeframes",
        lambda _: {"M5": pd.DataFrame({"close": [1.1000]})},
    )
    monkeypatch.setattr(
        detector_main.mt5,
        "get_current_quote",
        lambda _: {"bid": 1.0999, "ask": 1.1001, "mid": 1.1000},
    )
    monkeypatch.setattr(detector_main, "tracker_record", record)
    monkeypatch.setattr(detector_main, "send_signal", send)
    monkeypatch.setattr(detector_main, "_is_cooling_down", lambda _: False)
    monkeypatch.setattr(detector_main.stats, "tick", lambda: None)
    detector_main._last_sent.clear()


def test_tracker_failure_prevents_delivery(monkeypatch):
    calls = []

    def record(_):
        calls.append("record")
        raise RuntimeError("db unavailable")

    _prepare_pipeline(monkeypatch, record, lambda _: calls.append("send") or True)
    detector_main.scan_once()
    assert calls == ["record"]


def test_signal_is_tracked_before_delivery_with_spread(monkeypatch):
    calls = []

    def record(signal):
        calls.append("record")
        assert signal["meta"]["spread_pips"] == pytest.approx(2.0)
        assert REQUIRED_FIELDS <= signal.keys()

    _prepare_pipeline(monkeypatch, record, lambda _: calls.append("send") or True)
    detector_main.scan_once()
    assert calls == ["record", "send"]


@pytest.fixture
def strategy_config(monkeypatch):
    values = {
        "PIP": 0.0001,
        "SWING_LOOKBACK": 2,
        "OTE_LOW": 0.618,
        "OTE_HIGH": 0.786,
        "OTE_ENTRY_TOLERANCE_PIPS": 1.0,
        "SL_BUFFER_PIPS": 3.0,
        "FVG_MIN_SIZE_PIPS": 2.0,
        "OB_LOOKBACK": 30,
        "OTE_CONT_MIN_IMPULSE_PIPS": 25.0,
        "OTE_CONT_MIN_RISK_PIPS": 5.0,
        "OTE_CONT_BIAS_EMA": 20,
        "OTE_CONT_REQUIRE_FVG_OB": False,
        "PDH_PDL_LOOKBACK_M5": 24,
        "PDH_PDL_WICK_BODY_RATIO_MAX": 0.5,
        "PDH_PDL_MIN_RISK_PIPS": 5.0,
        "PDH_PDL_REQUIRE_BIAS": False,
        "PDH_PDL_REQUIRE_FVG_OB": False,
        "SILVER_BULLET_NY_START_HOUR": 10,
        "SILVER_BULLET_NY_END_HOUR": 11,
        "SILVER_BULLET_MIN_RISK_PIPS": 4.0,
        "SILVER_BULLET_REQUIRE_BIAS": False,
        "OVERLAP_BOS_NY_START_HOUR": 8,
        "OVERLAP_BOS_NY_END_HOUR": 10,
        "OVERLAP_BOS_FIB_LOW": 0.5,
        "OVERLAP_BOS_FIB_HIGH": 0.79,
        "OVERLAP_BOS_MIN_RISK_PIPS": 6.0,
        "OVERLAP_BOS_REQUIRE_BIAS": False,
        "OVERLAP_BOS_REQUIRE_FVG_OB": False,
        "BREAKER_LOOKBACK_M5": 50,
        "BREAKER_RETEST_TOLERANCE_PIPS": 1.0,
        "BREAKER_MIN_RISK_PIPS": 5.0,
        "BREAKER_REQUIRE_H1_BIAS_ALIGN": False,
        "JUDAS_REQUIRE_BIAS": False,
        "JUDAS_REQUIRE_FVG_OB": False,
        "LONDON_JUDAS_LOOKBACK_M5": 12,
        "LONDON_JUDAS_MIN_RANGE_PIPS": 15.0,
        "LONDON_JUDAS_MIN_RISK_PIPS": 5.0,
        "LONDON_JUDAS_BIAS_EMA": 20,
    }
    for name, value in values.items():
        monkeypatch.setattr(cfg, name, value)


@pytest.mark.parametrize(
    ("name", "scanner", "factory", "swing_lookback"),
    [
        ("london_judas", scan_judas, judas_data, 5),
        ("ote_continuation", scan_ote, ote_data, 2),
        ("pdh_pdl_sweep", scan_pdh, pdh_data, 2),
        ("silver_bullet", scan_silver, silver_data, 2),
        ("overlap_bos", scan_overlap, overlap_data, 2),
        ("breaker_flip", scan_breaker, breaker_data, 2),
    ],
)
def test_all_setups_emit_required_pipeline_fields(
    monkeypatch, strategy_config, name, scanner, factory, swing_lookback
):
    monkeypatch.setattr(cfg, "SWING_LOOKBACK", swing_lookback)
    signal = scanner(factory("long"))
    assert signal is not None
    signal["setup"] = name
    signal["killzone_match"] = True
    assert REQUIRED_FIELDS <= signal.keys()
    assert all(signal[field] is not None for field in REQUIRED_FIELDS)
