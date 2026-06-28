import os
import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from core.config import settings
from db import lifecycle


def test_relative_tracker_db_path_is_repo_anchored(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(settings, "TRACKER_DB_PATH", "data/eurotruck.db")

    expected = Path(__file__).resolve().parents[1] / "data" / "eurotruck.db"

    assert lifecycle._db_path() == expected.resolve()
    assert lifecycle._db_path() != (tmp_path / "data" / "eurotruck.db").resolve()


def test_absolute_tracker_db_path_is_returned_as_is(tmp_path, monkeypatch):
    absolute = tmp_path / "tracker.db"
    monkeypatch.setattr(settings, "TRACKER_DB_PATH", str(absolute))

    assert lifecycle._db_path() == absolute
