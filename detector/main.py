"""
XAUUSD ICT Bot — Nœud 1 Détecteur (Windows MT5)
Boucle de scan toutes les N secondes, envoie les signaux au backend via webhook.
"""
import logging
import os
import sys
import time
from logging.handlers import RotatingFileHandler
from datetime import datetime, timezone

import pytz
from apscheduler.schedulers.blocking import BlockingScheduler

import mt5_client as mt5
import stats
import strategy
import strategy.london_judas  # noqa: F401 -- triggers registry registration
import strategy.ote_continuation  # noqa: F401
import strategy.pdh_pdl_sweep  # noqa: F401
import strategy.silver_bullet  # noqa: F401
import strategy.overlap_bos  # noqa: F401
import strategy.breaker_flip  # noqa: F401
from config import cfg
from strategy import (
    minutes_to_next_killzone, get_active_killzone, runnable_setups,
)
from tracker import record_signal as tracker_record
from tracker import tick as tracker_tick
from tracker import init_db as tracker_init
from webhook import send_signal

os.makedirs("logs", exist_ok=True)

logging.basicConfig(
    level=getattr(logging, cfg.LOG_LEVEL.upper(), logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        RotatingFileHandler(
            "logs/detector.log",
            maxBytes=10 * 1024 * 1024,  # 10 MB
            backupCount=5,
            encoding="utf-8",
        ),
    ],
)
logging.getLogger("apscheduler").setLevel(logging.WARNING)
log = logging.getLogger("detector.main")

_last_sent: dict[str, datetime] = {}
_COOLDOWN_BY_SETUP = {}
_DEFAULT_COOLDOWN = 300


def _cooldown_key(signal: dict) -> str:
    return f"{signal['setup']}_{signal['direction']}_{signal['pattern']}"


def _is_cooling_down(signal: dict) -> bool:
    key = _cooldown_key(signal)
    last = _last_sent.get(key)
    if last is None:
        return False
    cooldown = _COOLDOWN_BY_SETUP.get(signal.get("setup"), _DEFAULT_COOLDOWN)
    elapsed = (datetime.now(tz=timezone.utc) - last).total_seconds()
    return elapsed < cooldown
def scan_once() -> None:
    now_utc = datetime.now(tz=timezone.utc)
    active_kz = get_active_killzone(now_utc)

    runnable = runnable_setups(active_kz)
    if not runnable:
        mins = minutes_to_next_killzone(now_utc)
        log.debug("No runnable setups (only required, outside killzone) — next in %d min", mins)
        return

    log.info("Scan — killzone=%s runnable=%d time=%s",
             active_kz, len(runnable), now_utc.strftime("%H:%M UTC"))

    if not mt5.is_connected():
        log.warning("MT5 disconnected — attempting reconnect")
        if not mt5.connect():
            log.error("Reconnect failed — skipping scan")
            return

    tf_data = mt5.get_all_timeframes(cfg.SYMBOL)
    if not tf_data or tf_data.get("M5") is None or tf_data["M5"].empty:
        log.warning("Could not fetch OHLC data")
        return

    for spec in runnable:
        try:
            signal = spec.scan(tf_data)
        except Exception:
            log.exception("Setup %s raised an exception — skip", spec.name)
            continue
        if signal is None:
            continue

        signal["setup"] = spec.name
        signal["killzone"] = active_kz
        signal["killzone_match"] = (
            spec.killzone_mode == "agnostic"
            or (active_kz is not None and active_kz in spec.killzones)
        )

        if _is_cooling_down(signal):
            log.debug("Cooldown active — %s", signal["setup"])
            continue

        log.info("SIGNAL %s %s — kz=%s match=%s",
                 signal["setup"], signal.get("direction"),
                 active_kz, signal["killzone_match"])
        send_signal(signal)
        try:
            tracker_record(signal)
        except Exception:
            log.exception("tracker_record failed — signal sent but not tracked")
        _last_sent[_cooldown_key(signal)] = now_utc

    stats.tick()


def heartbeat() -> None:
    now_utc = datetime.now(tz=timezone.utc)
    kz = get_active_killzone(now_utc)
    mins = minutes_to_next_killzone(now_utc)
    log.info(
        "HEARTBEAT — alive | mt5_connected=%s | killzone=%s | next_kz_in=%dmin",
        mt5.is_connected(), kz, mins,
    )


def main() -> None:
    import os
    os.makedirs("logs", exist_ok=True)

    log.info("=== XAUUSD ICT Detector starting ===")
    log.info("Symbol=%s  Killzones=%s  Interval=%ds",
             cfg.SYMBOL, cfg.ENABLED_KILLZONES, cfg.SCAN_INTERVAL_SECONDS)

    connected = False
    for i in range(1, cfg.MT5_INIT_RETRIES + 1):
        if mt5.connect():
            connected = True
            break
        log.warning("MT5 not ready — retry %d/%d in %ds",
                    i, cfg.MT5_INIT_RETRIES, cfg.MT5_INIT_RETRY_DELAY_SECONDS)
        time.sleep(cfg.MT5_INIT_RETRY_DELAY_SECONDS)

    if not connected:
        log.critical("Initial MT5 connection failed after %d retries — exiting",
                     cfg.MT5_INIT_RETRIES)
        sys.exit(1)

    scheduler = BlockingScheduler(timezone=pytz.utc)
    scheduler.add_job(
        scan_once,
        "interval",
        seconds=cfg.SCAN_INTERVAL_SECONDS,
        id="scan",
        next_run_time=datetime.now(tz=pytz.utc),
    )
    scheduler.add_job(heartbeat, "interval", minutes=cfg.HEARTBEAT_MINUTES, id="heartbeat")
    tracker_init()
    scheduler.add_job(
        lambda: tracker_tick(lambda: mt5.get_current_price(cfg.SYMBOL)),
        "interval", seconds=cfg.TRACKER_TICK_SECONDS, id="tracker_tick",
    )

    log.info("Scheduler started — scanning every %ds", cfg.SCAN_INTERVAL_SECONDS)
    try:
        scheduler.start()
    except KeyboardInterrupt:
        log.info("Detector stopped by user")
    finally:
        mt5.disconnect()


if __name__ == "__main__":
    main()
