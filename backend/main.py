"""
XAUUSD ICT Bot — Nœud 2 Backend FastAPI
Reçoit les signaux, enrichit avec news + LLM, push Telegram.
"""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from core.logger import setup_logging
from core.config import settings
from db.database import create_db
from api.signal import router as signal_router
from api.health import router as health_router
from api.logs import router as logs_router
from services.news.aggregator import refresh_news
from scheduler.news_refresh import start_news_scheduler

setup_logging()
log = logging.getLogger("backend.main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("=== XAUUSD Backend starting ===")
    create_db()
    log.info("DB initialized")

    # Initial news fetch
    log.info("Fetching initial news…")
    refresh_news()

    # Start background news refresh
    scheduler = start_news_scheduler()

    yield

    scheduler.shutdown(wait=False)
    log.info("Backend shutdown")


app = FastAPI(
    title="XAUUSD ICT Bot Backend",
    version="1.0.0",
    lifespan=lifespan,
)

app.include_router(signal_router)
app.include_router(health_router)
app.include_router(logs_router)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=settings.PORT, reload=False)
