import importlib.util
import sys
import types
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "detector"))

if "MetaTrader5" not in sys.modules:
    mt5_stub = types.SimpleNamespace(
        TIMEFRAME_M1=1,
        TIMEFRAME_M5=5,
        TIMEFRAME_M15=15,
        TIMEFRAME_H1=60,
        TIMEFRAME_H4=240,
        TIMEFRAME_D1=1440,
        initialize=lambda **_: True,
        last_error=lambda: (0, ""),
        symbol_select=lambda *_: True,
        account_info=lambda: None,
        shutdown=lambda: None,
        symbol_info=lambda _: None,
        terminal_info=lambda: None,
        copy_rates_from_pos=lambda *_: None,
        symbol_info_tick=lambda _: None,
    )
    sys.modules["MetaTrader5"] = mt5_stub


MAIN_SPEC = importlib.util.spec_from_file_location(
    "detector_scan_gate_main", ROOT / "detector" / "main.py"
)
assert MAIN_SPEC is not None and MAIN_SPEC.loader is not None
detector_main = importlib.util.module_from_spec(MAIN_SPEC)
MAIN_SPEC.loader.exec_module(detector_main)


def test_scan_skips_before_runnable_and_mt5_outside_killzone(monkeypatch):
    calls = []

    monkeypatch.setattr(detector_main, "get_active_killzone", lambda _: None)
    monkeypatch.setattr(detector_main, "minutes_to_next_killzone", lambda _: 42)
    monkeypatch.setattr(
        detector_main,
        "runnable_setups",
        lambda _: calls.append("runnable") or [],
    )
    monkeypatch.setattr(
        detector_main.mt5,
        "get_all_timeframes",
        lambda _: calls.append("ohlc") or {},
    )

    detector_main.scan_once()

    assert calls == []


def test_scan_proceeds_in_ny_pm(monkeypatch):
    calls = []
    spec = types.SimpleNamespace(
        name="dummy",
        scan=lambda _: calls.append("scan") or None,
        killzone_mode="required",
        killzones=("NY_PM",),
    )

    monkeypatch.setattr(detector_main, "get_active_killzone", lambda _: "NY_PM")
    monkeypatch.setattr(
        detector_main,
        "runnable_setups",
        lambda active_kz: calls.append(f"runnable:{active_kz}") or [spec],
    )
    monkeypatch.setattr(detector_main.mt5, "is_connected", lambda: True)
    monkeypatch.setattr(
        detector_main.mt5,
        "get_all_timeframes",
        lambda _: calls.append("ohlc") or {"M5": pd.DataFrame({"close": [1.1]})},
    )
    monkeypatch.setattr(detector_main.stats, "tick", lambda: calls.append("tick"))

    detector_main.scan_once()

    assert calls == ["runnable:NY_PM", "ohlc", "scan", "tick"]
