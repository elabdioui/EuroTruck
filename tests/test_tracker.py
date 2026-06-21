import sqlite3
import sys
from contextlib import closing
from pathlib import Path

import pytest


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "detector"))

from config import cfg
from tracker import get_open_signals, init_db, record_signal, tick


@pytest.fixture(autouse=True)
def tracker_db(tmp_path, monkeypatch):
    monkeypatch.setattr(cfg, "PIP", 0.0001)
    monkeypatch.setattr(cfg, "PARTIAL_TP_FRACTION", 0.5)
    monkeypatch.setattr(cfg, "MODEL_SPREAD_COST", True)
    init_db(tmp_path / "tracker.db")


def _signal(direction="long", entry=1.1000, sl=1.0990,
            tp1=1.1010, tp_final=1.1020):
    return {
        "setup": "dummy",
        "direction": direction,
        "pattern": "test_pattern",
        "killzone": "LONDON",
        "killzone_match": True,
        "entry": entry,
        "sl": sl,
        "tp1": tp1,
        "tp_final": tp_final,
    }


def _row(signal_id):
    rows = get_open_signals()
    if rows:
        return next(row for row in rows if row["id"] == signal_id)
    from tracker import core
    with closing(sqlite3.connect(core._db_path)) as connection:
        connection.row_factory = sqlite3.Row
        return dict(connection.execute(
            "SELECT * FROM signal_lifecycle WHERE id = ?", (signal_id,)
        ).fetchone())


def test_init_db_creates_schema(tmp_path):
    db_path = tmp_path / "schema.db"
    init_db(db_path)
    with closing(sqlite3.connect(db_path)) as connection:
        table = connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='signal_lifecycle'"
        ).fetchone()
        indexes = {
            row[0] for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='signal_lifecycle'"
            )
        }
    assert table is not None
    assert indexes == {
        "idx_lifecycle_status", "idx_lifecycle_setup", "idx_lifecycle_opened"
    }


def test_record_signal_inserts_row():
    signal_id = record_signal(_signal())
    row = _row(signal_id)
    assert row["status"] == "open"
    assert row["mfe_pips"] == 0
    assert row["mae_pips"] == 0
    assert row["risk_pips"] == pytest.approx(10)
    assert row["planned_rr"] == pytest.approx(2)
    assert row["entry_fill"] == pytest.approx(1.1000)
    assert row["spread_pips"] == 0
    assert row["extra_json"]


def test_record_signal_missing_field_raises():
    signal = _signal()
    del signal["entry"]
    with pytest.raises(ValueError, match="entry"):
        record_signal(signal)


def test_tick_updates_mfe_mae():
    signal_id = record_signal(_signal(tp1=1.1020, tp_final=1.1030))
    tick(lambda: 1.1010)
    row = _row(signal_id)
    assert row["mfe_pips"] == pytest.approx(10)
    assert row["mae_pips"] == 0
    assert row["status"] == "open"


def test_tick_partial_then_final_long():
    signal_id = record_signal(_signal())
    tick(lambda: 1.1010)
    partial = _row(signal_id)
    assert partial["status"] == "partial"
    assert partial["partial_at"] is not None

    tick(lambda: 1.1020)
    closed = _row(signal_id)
    assert closed["status"] == "closed_tp"
    assert closed["realized_r"] == pytest.approx(1.5)


def test_tick_sl_before_partial_short():
    signal_id = record_signal(_signal(
        direction="short", entry=1.1000, sl=1.1010,
        tp1=1.0990, tp_final=1.0980,
    ))
    tick(lambda: 1.1010)
    row = _row(signal_id)
    assert row["status"] == "closed_sl"
    assert row["realized_r"] == -1.0


def test_tick_sl_after_partial_long():
    signal_id = record_signal(_signal())
    tick(lambda: 1.1010)
    tick(lambda: 1.1000)
    row = _row(signal_id)
    assert row["status"] == "closed_be"
    assert row["realized_r"] == pytest.approx(0.5)


def test_known_spread_reduces_realized_r_net():
    signal = _signal()
    signal["entry_fill"] = 1.1001
    signal["meta"] = {"spread_pips": 2.0}
    signal_id = record_signal(signal)
    tick(lambda: {"bid": 1.0990, "ask": 1.0992, "mid": 1.0991})
    row = _row(signal_id)
    assert row["realized_r"] == -1.0
    assert row["realized_r_net"] == pytest.approx(-1.1)
