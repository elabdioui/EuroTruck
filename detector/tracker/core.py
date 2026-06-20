import json
import logging
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterator

try:
    from config import cfg
except ModuleNotFoundError:  # Support package imports from the repository root.
    from detector.config import cfg


log = logging.getLogger(__name__)

_REQUIRED_FIELDS = (
    "setup",
    "direction",
    "pattern",
    "entry",
    "sl",
    "tp1",
    "tp_final",
    "killzone_match",
)


def _resolve_db_path(db_path: str | Path) -> Path:
    path = Path(db_path)
    if path.is_absolute():
        return path
    return Path(__file__).resolve().parents[2] / path


_db_path = _resolve_db_path(cfg.TRACKER_DB_PATH)


def _utc_now() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


@contextmanager
def _connect() -> Iterator[sqlite3.Connection]:
    connection = sqlite3.connect(_db_path)
    connection.row_factory = sqlite3.Row
    try:
        with connection:
            yield connection
    finally:
        connection.close()


def init_db(db_path: str | Path | None = None) -> None:
    global _db_path

    configured_path = db_path if db_path is not None else cfg.TRACKER_DB_PATH
    _db_path = _resolve_db_path(configured_path)
    _db_path.parent.mkdir(parents=True, exist_ok=True)
    schema = Path(__file__).with_name("schema.sql").read_text(encoding="utf-8")
    with _connect() as connection:
        connection.executescript(schema)


def record_signal(signal: dict) -> int:
    missing = [field for field in _REQUIRED_FIELDS if signal.get(field) is None]
    if missing:
        log.warning("tracker_record rejected signal: missing fields %s", ", ".join(missing))
        raise ValueError(f"Missing required signal fields: {', '.join(missing)}")

    direction = str(signal["direction"]).lower()
    if direction not in {"long", "short"}:
        log.warning("tracker_record rejected signal: invalid direction %r", signal["direction"])
        raise ValueError("direction must be LONG or SHORT")

    entry = float(signal["entry"])
    sl = float(signal["sl"])
    tp_final = float(signal["tp_final"])
    pip = float(cfg.PIP)
    if pip <= 0:
        raise ValueError("cfg.PIP must be positive")

    risk = abs(entry - sl)
    if risk == 0:
        raise ValueError("entry and sl must differ")

    target_move = tp_final - entry if direction == "long" else entry - tp_final
    risk_pips = risk / pip
    planned_rr = target_move / risk
    now = _utc_now()
    payload = json.dumps(signal, default=str, sort_keys=True)

    with _connect() as connection:
        cursor = connection.execute(
            """
            INSERT INTO signal_lifecycle (
                setup, direction, pattern, killzone, killzone_match,
                entry, sl, tp1, tp_final, risk_pips, planned_rr,
                status, mfe_pips, mae_pips, realized_r,
                opened_at, partial_at, closed_at, last_tick_at, extra_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'open', 0, 0, NULL,
                      ?, NULL, NULL, ?, ?)
            """,
            (
                str(signal["setup"]),
                direction,
                str(signal["pattern"]),
                signal.get("killzone"),
                int(bool(signal["killzone_match"])),
                entry,
                sl,
                float(signal["tp1"]),
                tp_final,
                risk_pips,
                planned_rr,
                now,
                now,
                payload,
            ),
        )
        return int(cursor.lastrowid)


def get_open_signals() -> list[dict]:
    with _connect() as connection:
        rows = connection.execute(
            "SELECT * FROM signal_lifecycle WHERE status IN ('open', 'partial') ORDER BY id"
        ).fetchall()
    return [dict(row) for row in rows]


def _level_hit(direction: str, price: float, level: float, kind: str) -> bool:
    if kind == "sl":
        return price <= level if direction == "long" else price >= level
    return price >= level if direction == "long" else price <= level


def _tick_signal(signal: dict, current_price: float) -> None:
    direction = signal["direction"]
    entry = float(signal["entry"])
    excursion = (
        current_price - entry if direction == "long" else entry - current_price
    ) / float(cfg.PIP)
    mfe_pips = max(float(signal["mfe_pips"]), excursion)
    mae_pips = min(float(signal["mae_pips"]), excursion)
    status = signal["status"]
    partial_at = signal["partial_at"]
    closed_at = signal["closed_at"]
    realized_r = signal["realized_r"]
    now = _utc_now()

    effective_sl = entry if status == "partial" else float(signal["sl"])
    if _level_hit(direction, current_price, effective_sl, "sl"):
        if status == "partial":
            status = "closed_be"
            realized_r = float(cfg.PARTIAL_TP_FRACTION)
        else:
            status = "closed_sl"
            realized_r = -1.0
        closed_at = now
    else:
        if status == "open" and _level_hit(
            direction, current_price, float(signal["tp1"]), "tp"
        ):
            status = "partial"
            partial_at = now
            realized_r = float(cfg.PARTIAL_TP_FRACTION)

        if status == "partial" and _level_hit(
            direction, current_price, float(signal["tp_final"]), "tp"
        ):
            status = "closed_tp"
            realized_r = float(cfg.PARTIAL_TP_FRACTION) + (
                (1.0 - float(cfg.PARTIAL_TP_FRACTION)) * float(signal["planned_rr"])
            )
            closed_at = now

    with _connect() as connection:
        connection.execute(
            """
            UPDATE signal_lifecycle
            SET status = ?, mfe_pips = ?, mae_pips = ?, realized_r = ?,
                partial_at = ?, closed_at = ?, last_tick_at = ?
            WHERE id = ?
            """,
            (
                status,
                mfe_pips,
                mae_pips,
                realized_r,
                partial_at,
                closed_at,
                now,
                signal["id"],
            ),
        )


def tick(get_price_callable: Callable[[], float]) -> None:
    try:
        signals = get_open_signals()
        if not signals:
            return

        for signal in signals:
            try:
                current_price = get_price_callable()
                if current_price is None:
                    log.warning("tracker_tick skipped signal %s: current price unavailable", signal["id"])
                    continue
                _tick_signal(signal, float(current_price))
            except Exception:
                log.exception("tracker_tick failed for signal %s", signal.get("id"))
    except Exception:
        log.exception("tracker_tick failed")
