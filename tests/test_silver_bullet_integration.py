import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "detector"))

from config import cfg
from strategy.silver_bullet import NAME, scan
from tracker import get_open_signals, init_db, record_signal
from test_silver_bullet import valid_tf_data


def test_signal_recorded_in_tracker(tmp_path, monkeypatch):
    monkeypatch.setattr(cfg, "PIP", 0.0001)
    monkeypatch.setattr(cfg, "FVG_MIN_SIZE_PIPS", 2.0)
    monkeypatch.setattr(cfg, "SILVER_BULLET_NY_START_HOUR", 10)
    monkeypatch.setattr(cfg, "SILVER_BULLET_NY_END_HOUR", 11)
    monkeypatch.setattr(cfg, "SILVER_BULLET_MIN_RISK_PIPS", 4.0)
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
