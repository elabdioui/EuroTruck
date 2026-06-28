"""Read-only access to the detector tracker's lifecycle database."""

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


def _db_path() -> Path:
    from core.config import settings

    raw = Path(settings.TRACKER_DB_PATH)
    if raw.is_absolute():
        return raw
    # Anchor relative tracker paths on the repository root, matching
    # detector/tracker/core.py._resolve_db_path regardless of backend CWD.
    return (Path(__file__).resolve().parents[2] / raw).resolve()


@contextmanager
def ro_connect() -> Iterator[sqlite3.Connection]:
    path = _db_path()
    if not path.exists():
        raise FileNotFoundError(f"Tracker DB not found: {path}")
    connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        yield connection
    finally:
        connection.close()
