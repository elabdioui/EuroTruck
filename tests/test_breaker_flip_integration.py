import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "detector"))

from config import cfg
from strategy.breaker_flip import NAME, scan
from tracker import get_open_signals, init_db, record_signal
from test_breaker_flip import valid_tf_data


def test_signal_recorded_in_tracker(tmp_path, monkeypatch):
    monkeypatch.setattr(cfg, "PIP", 0.0001)
    monkeypatch.setattr(cfg, "OB_LOOKBACK", 30)
    monkeypatch.setattr(cfg, "SL_BUFFER_PIPS", 3.0)
    monkeypatch.setattr(cfg, "BREAKER_LOOKBACK_M5", 50)
    monkeypatch.setattr(cfg, "BREAKER_RETEST_TOLERANCE_PIPS", 1.0)
    monkeypatch.setattr(cfg, "BREAKER_MIN_RISK_PIPS", 5.0)
    monkeypatch.setattr(cfg, "BREAKER_REQUIRE_H1_BIAS_ALIGN", False)
    init_db(tmp_path / "integration.db")

    signal = scan(valid_tf_data("long"))
    assert signal is not None
    signal["setup"] = NAME
    signal["killzone"] = "NY_AM"
    signal["killzone_match"] = True
    record_signal(signal)

    rows = get_open_signals()
    assert len(rows) == 1
    assert rows[0]["setup"] == NAME
    assert rows[0]["status"] == "open"
