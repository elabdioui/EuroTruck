import logging
import pandas as pd
import MetaTrader5 as mt5
from datetime import datetime

from config import cfg

log = logging.getLogger(__name__)

_TIMEFRAME_MAP = {
    "M1": mt5.TIMEFRAME_M1,
    "M5": mt5.TIMEFRAME_M5,
    "M15": mt5.TIMEFRAME_M15,
    "H1": mt5.TIMEFRAME_H1,
    "H4": mt5.TIMEFRAME_H4,
    "D1": mt5.TIMEFRAME_D1,
}


def connect() -> bool:
    if not mt5.initialize(
        login=cfg.MT5_LOGIN,
        password=cfg.MT5_PASSWORD,
        server=cfg.MT5_SERVER,
    ):
        log.error("MT5 init failed: %s", mt5.last_error())
        return False
    info = mt5.terminal_info()
    log.info("MT5 connected — build %s, connected=%s", info.build, info.connected)
    return True


def disconnect() -> None:
    mt5.shutdown()


def is_connected() -> bool:
    info = mt5.terminal_info()
    return info is not None and info.connected


def get_ohlc(symbol: str, timeframe: str, count: int) -> pd.DataFrame:
    tf = _TIMEFRAME_MAP.get(timeframe)
    if tf is None:
        raise ValueError(f"Unknown timeframe: {timeframe}")

    rates = mt5.copy_rates_from_pos(symbol, tf, 0, count)
    if rates is None or len(rates) == 0:
        log.warning("No data for %s %s — %s", symbol, timeframe, mt5.last_error())
        return pd.DataFrame()

    df = pd.DataFrame(rates)
    df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
    df = df.rename(columns={"tick_volume": "volume"})
    df = df[["time", "open", "high", "low", "close", "volume"]].reset_index(drop=True)
    return df


def get_current_price(symbol: str) -> float | None:
    tick = mt5.symbol_info_tick(symbol)
    if tick is None:
        return None
    return (tick.bid + tick.ask) / 2


def get_all_timeframes(symbol: str) -> dict[str, pd.DataFrame]:
    return {
        "M1": get_ohlc(symbol, "M1", cfg.OHLC_COUNT_M1),
        "M5": get_ohlc(symbol, "M5", cfg.OHLC_COUNT_M5),
        "M15": get_ohlc(symbol, "M15", cfg.OHLC_COUNT_M15),
        "H1": get_ohlc(symbol, "H1", cfg.OHLC_COUNT_H1),
        "H4": get_ohlc(symbol, "H4", cfg.OHLC_COUNT_H4),
        "D1": get_ohlc(symbol, "D1", cfg.OHLC_COUNT_D1),
    }
