import os
from dotenv import load_dotenv

load_dotenv()


class Settings:
    WEBHOOK_HMAC_SECRET: str = os.getenv("WEBHOOK_HMAC_SECRET", "")

    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
    GROQ_API_KEY: str = os.getenv("GROQ_API_KEY", "")
    LLM_PRIMARY: str = os.getenv("LLM_PRIMARY", "gemini")
    LLM_TIMEOUT_SECONDS: int = int(os.getenv("LLM_TIMEOUT_SECONDS", "5"))

    TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
    TELEGRAM_CHAT_ID: str = os.getenv("TELEGRAM_CHAT_ID", "")

    FOREX_FACTORY_URL: str = os.getenv(
        "FOREX_FACTORY_URL", "https://www.forexfactory.com/calendar"
    )
    NEWS_REFRESH_MINUTES: int = int(os.getenv("NEWS_REFRESH_MINUTES", "5"))
    NEWS_RED_BLOCK_WINDOW_MIN: int = int(os.getenv("NEWS_RED_BLOCK_WINDOW_MIN", "15"))

    DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite:///./alerts.db")

    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
    PORT: int = int(os.getenv("PORT", "8000"))
    API_SECRET_TOKEN: str = os.getenv("API_SECRET_TOKEN", "")


settings = Settings()
