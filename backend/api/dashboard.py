"""Read-only lifecycle dashboard endpoints."""

import csv
import json
import sqlite3
from contextlib import contextmanager
from io import BytesIO, StringIO
from typing import Iterator

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from openpyxl import Workbook

from db.lifecycle import ro_connect


router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])

_CLOSED = ("closed_tp", "closed_be", "closed_sl", "closed_timeout")
_EXPORT_COLUMNS = (
    "id", "setup", "direction", "pattern", "killzone", "killzone_match",
    "entry", "entry_fill", "spread_pips", "sl", "tp1", "tp_final",
    "risk_pips", "planned_rr", "status", "mfe_pips", "mae_pips",
    "realized_r", "realized_r_net", "opened_at", "partial_at", "closed_at",
)


@contextmanager
def _connect() -> Iterator[sqlite3.Connection]:
    try:
        with ro_connect() as connection:
            yield connection
    except FileNotFoundError as exc:
        raise HTTPException(503, "Tracker DB not yet initialized") from exc
    except sqlite3.OperationalError as exc:
        if "no such table" in str(exc).lower():
            raise HTTPException(503, "Tracker DB not yet initialized") from exc
        raise


def _filters(status: str | None, setup: str | None) -> tuple[str, list[str]]:
    clauses: list[str] = []
    values: list[str] = []
    if status is not None:
        clauses.append("status = ?")
        values.append(status)
    if setup is not None:
        clauses.append("setup = ?")
        values.append(setup)
    return (" WHERE " + " AND ".join(clauses) if clauses else ""), values


def _rate(numerator: int, denominator: int) -> float:
    return float(numerator / denominator) if denominator else 0.0


def _row(row: sqlite3.Row) -> dict:
    return dict(row)


@router.get("/summary")
def summary() -> dict:
    with _connect() as connection:
        row = connection.execute(
            """
            SELECT COUNT(*) AS total_signals,
                   COALESCE(SUM(CASE WHEN status = 'open' THEN 1 ELSE 0 END), 0) AS open_count,
                   COALESCE(SUM(CASE WHEN status = 'partial' THEN 1 ELSE 0 END), 0) AS partial_count,
                   COALESCE(SUM(CASE WHEN status = 'closed_tp' THEN 1 ELSE 0 END), 0) AS tp_count,
                   COALESCE(SUM(CASE WHEN status = 'closed_be' THEN 1 ELSE 0 END), 0) AS be_count,
                   COALESCE(SUM(CASE WHEN status = 'closed_sl' THEN 1 ELSE 0 END), 0) AS sl_count,
                   COALESCE(SUM(CASE WHEN status = 'closed_timeout' THEN 1 ELSE 0 END), 0) AS timeout_count,
                   COALESCE(SUM(CASE WHEN status IN ('closed_tp', 'closed_be', 'closed_sl', 'closed_timeout')
                                     THEN realized_r ELSE 0 END), 0) AS net_r,
                   MIN(opened_at) AS first_signal_at,
                   MAX(opened_at) AS last_signal_at
            FROM signal_lifecycle
            """
        ).fetchone()
    data = _row(row)
    closed = int(data["tp_count"] + data["be_count"] + data["sl_count"] + data["timeout_count"])
    net_r = float(data["net_r"])
    return {
        "total_signals": int(data["total_signals"]),
        "open": int(data["open_count"]),
        "partial": int(data["partial_count"]),
        "closed_tp": int(data["tp_count"]),
        "closed_be": int(data["be_count"]),
        "closed_sl": int(data["sl_count"]),
        "closed_timeout": int(data["timeout_count"]),
        "win_rate": _rate(int(data["tp_count"]), closed),
        "net_r": net_r,
        "avg_r": _rate(net_r, closed),
        "first_signal_at": data["first_signal_at"],
        "last_signal_at": data["last_signal_at"],
    }


@router.get("/setups")
def by_setup() -> list[dict]:
    with _connect() as connection:
        rows = connection.execute(
            """
            SELECT setup, COUNT(*) AS total,
                   SUM(CASE WHEN status = 'open' THEN 1 ELSE 0 END) AS open_count,
                   SUM(CASE WHEN status = 'partial' THEN 1 ELSE 0 END) AS partial_count,
                   SUM(CASE WHEN status = 'closed_tp' THEN 1 ELSE 0 END) AS tp_count,
                   SUM(CASE WHEN status = 'closed_be' THEN 1 ELSE 0 END) AS be_count,
                   SUM(CASE WHEN status = 'closed_sl' THEN 1 ELSE 0 END) AS sl_count,
                   SUM(CASE WHEN status = 'closed_timeout' THEN 1 ELSE 0 END) AS timeout_count,
                   COALESCE(SUM(CASE WHEN status IN ('closed_tp', 'closed_be', 'closed_sl', 'closed_timeout')
                                     THEN realized_r ELSE 0 END), 0) AS net_r,
                   COALESCE(AVG(mfe_pips), 0) AS avg_mfe_pips,
                   COALESCE(AVG(mae_pips), 0) AS avg_mae_pips
            FROM signal_lifecycle GROUP BY setup ORDER BY setup
            """
        ).fetchall()
    result = []
    for row in rows:
        data = _row(row)
        closed = int(data["tp_count"] + data["be_count"] + data["sl_count"] + data["timeout_count"])
        net_r = float(data["net_r"])
        result.append({
            "setup": data["setup"], "total": int(data["total"]),
            "open": int(data["open_count"]), "partial": int(data["partial_count"]),
            "closed_tp": int(data["tp_count"]), "closed_be": int(data["be_count"]),
            "closed_sl": int(data["sl_count"]),
            "closed_timeout": int(data["timeout_count"]),
            "win_rate": _rate(int(data["tp_count"]), closed),
            "net_r": net_r, "avg_r": _rate(net_r, closed),
            "avg_mfe_pips": float(data["avg_mfe_pips"]),
            "avg_mae_pips": float(data["avg_mae_pips"]),
        })
    return result


@router.get("/signals")
def list_signals(
    status: str | None = Query(None),
    setup: str | None = Query(None),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> dict:
    where, values = _filters(status, setup)
    with _connect() as connection:
        total = connection.execute(
            "SELECT COUNT(*) FROM signal_lifecycle" + where, values
        ).fetchone()[0]
        rows = connection.execute(
            "SELECT * FROM signal_lifecycle" + where
            + " ORDER BY opened_at DESC, id DESC LIMIT ? OFFSET ?",
            [*values, limit, offset],
        ).fetchall()
    items = []
    for row in rows:
        item = _row(row)
        item.pop("extra_json", None)
        items.append(item)
    return {"total": int(total), "limit": limit, "offset": offset, "items": items}


@router.get("/signals/{signal_id}")
def signal_detail(signal_id: int) -> dict:
    with _connect() as connection:
        row = connection.execute(
            "SELECT * FROM signal_lifecycle WHERE id = ?", (signal_id,)
        ).fetchone()
    if row is None:
        raise HTTPException(404, "Signal not found")
    result = _row(row)
    if result["extra_json"]:
        try:
            result["extra_json"] = json.loads(result["extra_json"])
        except json.JSONDecodeError:
            result["extra_json"] = None
    return result


def _export_rows(status: str | None, setup: str | None) -> list[dict]:
    where, values = _filters(status, setup)
    columns = ", ".join(_EXPORT_COLUMNS)
    with _connect() as connection:
        rows = connection.execute(
            f"SELECT {columns} FROM signal_lifecycle{where} ORDER BY opened_at DESC, id DESC",
            values,
        ).fetchall()
    return [_row(row) for row in rows]


@router.get("/export.csv")
def export_csv(status: str | None = None, setup: str | None = None) -> StreamingResponse:
    output = StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=_EXPORT_COLUMNS)
    writer.writeheader()
    writer.writerows(_export_rows(status, setup))
    return StreamingResponse(
        iter([output.getvalue()]), media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=eurotruck-signals.csv"},
    )


@router.get("/export.xlsx")
def export_xlsx(status: str | None = None, setup: str | None = None) -> StreamingResponse:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Signals"
    sheet.append(list(_EXPORT_COLUMNS))
    for row in _export_rows(status, setup):
        sheet.append([row[column] for column in _EXPORT_COLUMNS])
    output = BytesIO()
    workbook.save(output)
    output.seek(0)
    return StreamingResponse(
        output,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=eurotruck-signals.xlsx"},
    )
