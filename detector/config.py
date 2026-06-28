import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env from root (VPS mono-machine) then fall back to local detector/.env
_root_env = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(dotenv_path=_root_env if _root_env.exists() else None)


class Config:
    MT5_LOGIN: int = int(os.getenv("MT5_LOGIN", "0"))
    MT5_PASSWORD: str = os.getenv("MT5_PASSWORD", "")
    MT5_SERVER: str = os.getenv("MT5_SERVER", "")
    MT5_PATH: str = os.getenv("MT5_PATH", "")
    MT5_INIT_RETRIES: int = int(os.getenv("MT5_INIT_RETRIES", "10"))
    MT5_INIT_RETRY_DELAY_SECONDS: int = int(os.getenv("MT5_INIT_RETRY_DELAY_SECONDS", "30"))
    HEARTBEAT_MINUTES: int = int(os.getenv("HEARTBEAT_MINUTES", "15"))

    SYMBOL: str = os.getenv("SYMBOL", "EURUSDm")
    PIP: float = 0.0001  # safe EURUSD default; resolved from the live symbol at startup
    SCAN_INTERVAL_SECONDS: int = int(os.getenv("SCAN_INTERVAL_SECONDS", "30"))
    TRACKER_DB_PATH: str = os.getenv("TRACKER_DB_PATH", "data/eurotruck.db")
    TRACKER_TICK_SECONDS: int = int(os.getenv("TRACKER_TICK_SECONDS", "30"))
    PARTIAL_TP_FRACTION: float = float(os.getenv("PARTIAL_TP_FRACTION", "0.5"))
    MODEL_SPREAD_COST: bool = os.getenv("MODEL_SPREAD_COST", "true").lower() == "true"
    TRADE_MAX_AGE_HOURS: float = float(os.getenv("TRADE_MAX_AGE_HOURS", "48"))

    BACKEND_WEBHOOK_URL: str = os.getenv("BACKEND_WEBHOOK_URL", "")
    WEBHOOK_HMAC_SECRET: str = os.getenv("WEBHOOK_HMAC_SECRET", "")

    ENABLED_KILLZONES: list[str] = os.getenv(
        "ENABLED_KILLZONES", "LONDON,NY_AM,NY_PM"
    ).split(",")

    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")

    # Candle counts per timeframe for OHLC fetch
    OHLC_COUNT_M1: int = 200
    OHLC_COUNT_M5: int = 200
    OHLC_COUNT_M15: int = 100
    OHLC_COUNT_H1: int = 100
    OHLC_COUNT_H4: int = 60
    OHLC_COUNT_D1: int = 30

    # ICT params
    FVG_MIN_SIZE_PIPS: float = 2.0      # minimum FVG size in symbol-driven pips
    OB_MIN_BODY_PIPS: float = 1.0       # doji filter; mirrors gold's 1-pip intent. Starting hypothesis.
    OB_LOOKBACK: int = 30               # candles to look back for OB detection
    LIQUIDITY_EQUAL_TOLERANCE_PIPS: float = float(
        os.getenv("LIQUIDITY_EQUAL_TOLERANCE_PIPS", "1")
    )
    LIQUIDITY_SWEEP_LOOKBACK_M5: int = int(
        os.getenv("LIQUIDITY_SWEEP_LOOKBACK_M5", "30")
    )
    SWING_LOOKBACK: int = 5             # candles each side for swing detection
    OTE_LOW: float = 0.618              # shallow OTE boundary (Fibonacci ratio)
    OTE_HIGH: float = 0.786             # deep OTE boundary   (Fibonacci ratio)
    OTE_ENTRY_TOLERANCE_PIPS: float = float(os.getenv("OTE_ENTRY_TOLERANCE_PIPS", "1.0"))
    LONDON_JUDAS_LOOKBACK_M5: int = int(os.getenv("LONDON_JUDAS_LOOKBACK_M5", "12"))
    LONDON_JUDAS_MIN_RANGE_PIPS: float = float(os.getenv("LONDON_JUDAS_MIN_RANGE_PIPS", "15"))
    LONDON_JUDAS_MIN_RISK_PIPS: float = float(os.getenv("LONDON_JUDAS_MIN_RISK_PIPS", "5"))
    LONDON_JUDAS_BIAS_EMA: int = int(os.getenv("LONDON_JUDAS_BIAS_EMA", "20"))
    JUDAS_REQUIRE_BIAS: bool = os.getenv(
        "JUDAS_REQUIRE_BIAS", "false"
    ).lower() == "true"
    JUDAS_REQUIRE_FVG_OB: bool = os.getenv(
        "JUDAS_REQUIRE_FVG_OB", "false"
    ).lower() == "true"
    OTE_CONT_MIN_IMPULSE_PIPS: float = float(os.getenv("OTE_CONT_MIN_IMPULSE_PIPS", "25"))
    OTE_CONT_MIN_RISK_PIPS: float = float(os.getenv("OTE_CONT_MIN_RISK_PIPS", "5"))
    OTE_CONT_BIAS_EMA: int = int(os.getenv("OTE_CONT_BIAS_EMA", "20"))
    OTE_CONT_REQUIRE_FVG_OB: bool = os.getenv(
        "OTE_CONT_REQUIRE_FVG_OB", "false"
    ).lower() == "true"
    PDH_PDL_LOOKBACK_M5: int = int(os.getenv("PDH_PDL_LOOKBACK_M5", "24"))
    PDH_PDL_WICK_BODY_RATIO_MAX: float = float(os.getenv("PDH_PDL_WICK_BODY_RATIO_MAX", "0.5"))
    PDH_PDL_MIN_RISK_PIPS: float = float(os.getenv("PDH_PDL_MIN_RISK_PIPS", "5"))
    PDH_PDL_REQUIRE_BIAS: bool = os.getenv(
        "PDH_PDL_REQUIRE_BIAS", "false"
    ).lower() == "true"
    PDH_PDL_REQUIRE_FVG_OB: bool = os.getenv(
        "PDH_PDL_REQUIRE_FVG_OB", "false"
    ).lower() == "true"
    SILVER_BULLET_NY_START_HOUR: int = int(os.getenv("SILVER_BULLET_NY_START_HOUR", "10"))
    SILVER_BULLET_NY_END_HOUR: int = int(os.getenv("SILVER_BULLET_NY_END_HOUR", "11"))
    SILVER_BULLET_MIN_RISK_PIPS: float = float(os.getenv("SILVER_BULLET_MIN_RISK_PIPS", "4"))
    SILVER_BULLET_REQUIRE_BIAS: bool = os.getenv(
        "SILVER_BULLET_REQUIRE_BIAS", "false"
    ).lower() == "true"
    OVERLAP_BOS_NY_START_HOUR: int = int(os.getenv("OVERLAP_BOS_NY_START_HOUR", "8"))
    OVERLAP_BOS_NY_END_HOUR: int = int(os.getenv("OVERLAP_BOS_NY_END_HOUR", "10"))
    OVERLAP_BOS_FIB_LOW: float = float(os.getenv("OVERLAP_BOS_FIB_LOW", "0.5"))
    OVERLAP_BOS_FIB_HIGH: float = float(os.getenv("OVERLAP_BOS_FIB_HIGH", "0.79"))
    OVERLAP_BOS_MIN_RISK_PIPS: float = float(os.getenv("OVERLAP_BOS_MIN_RISK_PIPS", "6"))
    OVERLAP_BOS_REQUIRE_BIAS: bool = os.getenv(
        "OVERLAP_BOS_REQUIRE_BIAS", "false"
    ).lower() == "true"
    OVERLAP_BOS_REQUIRE_FVG_OB: bool = os.getenv(
        "OVERLAP_BOS_REQUIRE_FVG_OB", "false"
    ).lower() == "true"
    BREAKER_LOOKBACK_M5: int = int(os.getenv("BREAKER_LOOKBACK_M5", "50"))
    BREAKER_RETEST_TOLERANCE_PIPS: float = float(os.getenv("BREAKER_RETEST_TOLERANCE_PIPS", "1"))
    BREAKER_MIN_RISK_PIPS: float = float(os.getenv("BREAKER_MIN_RISK_PIPS", "5"))
    BREAKER_REQUIRE_H1_BIAS_ALIGN: bool = os.getenv(
        "BREAKER_REQUIRE_H1_BIAS_ALIGN", "false"
    ).lower() == "true"
    SL_BUFFER_PIPS: float = 3.0  # used as SL_BUFFER_PIPS * Config.PIP in new setups
    
cfg = Config()
