"""APScheduler job: refresh news cache every N minutes."""
import logging
from apscheduler.schedulers.background import BackgroundScheduler
from services.news.aggregator import refresh_news
from core.config import settings

log = logging.getLogger(__name__)


def start_news_scheduler() -> BackgroundScheduler:
    scheduler = BackgroundScheduler()
    scheduler.add_job(
        refresh_news,
        "interval",
        minutes=settings.NEWS_REFRESH_MINUTES,
        id="news_refresh",
        next_run_time=None,  # run immediately on first call from startup
    )
    scheduler.start()
    log.info("News scheduler started — refresh every %dmin", settings.NEWS_REFRESH_MINUTES)
    return scheduler
