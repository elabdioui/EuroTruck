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
        columns = {
            row[1] for row in connection.execute("PRAGMA table_info(signal_lifecycle)")
        }
        migrations = {
            "entry_fill": "REAL",
            "spread_pips": "REAL NOT NULL DEFAULT 0",
            "realized_r_net": "REAL",
        }
        for name, definition in migrations.items():
            if name not in columns:
                connection.execute(
                    f"ALTER TABLE signal_lifecycle ADD COLUMN {name} {definition}"
                )
        connection.execute(
            "UPDATE signal_lifecycle SET entry_fill = entry WHERE entry_fill IS NULL"
        )


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
    entry_fill = float(signal.get("entry_fill", entry))
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
    spread_pips = signal.get("meta", {}).get("spread_pips")
    spread_pips = 0.0 if spread_pips is None else float(spread_pips)

    with _connect() as connection:
        cursor = connection.execute(
            """
            INSERT INTO signal_lifecycle (
                setup, direction, pattern, killzone, killzone_match,
                entry, entry_fill, spread_pips, sl, tp1, tp_final, risk_pips, planned_rr,
                status, mfe_pips, mae_pips, realized_r, realized_r_net,
                opened_at, partial_at, closed_at, last_tick_at, extra_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'open', 0, 0, NULL, NULL,
                      ?, NULL, NULL, ?, ?)
            """,
            (
                str(signal["setup"]),
                direction,
                str(signal["pattern"]),
                signal.get("killzone"),
                int(bool(signal["killzone_match"])),
                entry,
                entry_fill,
                spread_pips,
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


def _quote_prices(value) -> tuple[float, float, float]:
    if isinstance(value, dict):
        bid = float(value["bid"])
        ask = float(value["ask"])
        return bid, ask, float(value.get("mid", (bid + ask) / 2.0))
    price = float(value)
    return price, price, price


def _net_realized_r(signal: dict, status: str) -> float | None:
    if not cfg.MODEL_SPREAD_COST:
        return signal.get("realized_r")
    direction = signal["direction"]
    entry = float(signal["entry"])
    entry_fill = float(signal.get("entry_fill") or entry)
    risk = abs(entry - float(signal["sl"]))
    if risk <= 0:
        return None

    def net_at(price: float) -> float:
        move = price - entry_fill if direction == "long" else entry_fill - price
        return move / risk

    fraction = float(cfg.PARTIAL_TP_FRACTION)
    if status == "closed_sl":
        return net_at(float(signal["sl"]))
    if status in {"partial", "closed_be"}:
        return fraction * net_at(float(signal["tp1"])) + (
            (1.0 - fraction) * net_at(entry)
        )
    if status == "closed_tp":
        return fraction * net_at(float(signal["tp1"])) + (
            (1.0 - fraction) * net_at(float(signal["tp_final"]))
        )
    return None


def _tick_signal(signal: dict, quote) -> None:
    direction = signal["direction"]
    entry = float(signal["entry"])
    bid, ask, mid = _quote_prices(quote)
    current_price = (
        bid if cfg.MODEL_SPREAD_COST and direction == "long"
        else ask if cfg.MODEL_SPREAD_COST and direction == "short"
        else mid
    )
    excursion = (
        current_price - entry if direction == "long" else entry - current_price
    ) / float(cfg.PIP)
    mfe_pips = max(float(signal["mfe_pips"]), excursion)
    mae_pips = min(float(signal["mae_pips"]), excursion)
    status = signal["status"]
    partial_at = signal["partial_at"]
    closed_at = signal["closed_at"]
    realized_r = signal["realized_r"]
    realized_r_net = signal.get("realized_r_net")
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

    realized_r_net = _net_realized_r({**signal, "realized_r": realized_r}, status)

    with _connect() as connection:
        connection.execute(
            """
            UPDATE signal_lifecycle
            SET status = ?, mfe_pips = ?, mae_pips = ?, realized_r = ?, realized_r_net = ?,
                partial_at = ?, closed_at = ?, last_tick_at = ?
            WHERE id = ?
            """,
            (
                status,
                mfe_pips,
                mae_pips,
                realized_r,
                realized_r_net,
                partial_at,
                closed_at,
                now,
                signal["id"],
            ),
        )


def tick(get_price_callable: Callable[[], object]) -> None:
    try:
        signals = get_open_signals()
        if not signals:
            return

        for signal in signals:
            try:
                quote = get_price_callable()
                if quote is None:
                    log.warning("tracker_tick skipped signal %s: current price unavailable", signal["id"])
                    continue
                _tick_signal(signal, quote)
            except Exception:
                log.exception("tracker_tick failed for signal %s", signal.get("id"))
    except Exception:
        log.exception("tracker_tick failed")
