import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "detector"))

from config import cfg
from strategy.overlap_bos import NAME, scan
from tracker import get_open_signals, init_db, record_signal
from test_overlap_bos import valid_tf_data


def test_signal_recorded_in_tracker(tmp_path, monkeypatch):
    monkeypatch.setattr(cfg, "PIP", 0.0001)
    monkeypatch.setattr(cfg, "SWING_LOOKBACK", 2)
    monkeypatch.setattr(cfg, "OTE_ENTRY_TOLERANCE_PIPS", 1.0)
    monkeypatch.setattr(cfg, "OVERLAP_BOS_NY_START_HOUR", 8)
    monkeypatch.setattr(cfg, "OVERLAP_BOS_NY_END_HOUR", 10)
    monkeypatch.setattr(cfg, "OVERLAP_BOS_FIB_LOW", 0.5)
    monkeypatch.setattr(cfg, "OVERLAP_BOS_FIB_HIGH", 0.79)
    monkeypatch.setattr(cfg, "OVERLAP_BOS_MIN_RISK_PIPS", 6.0)
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
