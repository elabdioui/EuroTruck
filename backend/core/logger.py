import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path
from core.config import settings

LOG_FILE = Path(__file__).resolve().parent.parent / "logs" / "bot.log"


def setup_logging() -> None:
    LOG_FILE.parent.mkdir(exist_ok=True)
    fmt = "%(asctime)s [%(levelname)s] %(name)s — %(message)s"
    handlers: list[logging.Handler] = [
        logging.StreamHandler(sys.stdout),
        RotatingFileHandler(LOG_FILE, maxBytes=2 * 1024 * 1024, backupCount=3, encoding="utf-8"),
    ]
    logging.basicConfig(level=settings.LOG_LEVEL, format=fmt, handlers=handlers)
