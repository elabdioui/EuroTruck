"""Telegram bot client — sends formatted messages."""
import logging

import httpx

from core.config import settings

log = logging.getLogger(__name__)

_BASE = "https://api.telegram.org/bot{token}/{method}"


def _api_url(method: str) -> str:
    return _BASE.format(token=settings.TELEGRAM_BOT_TOKEN, method=method)


def send_message(text: str, parse_mode: str = "HTML") -> int | None:
    """Send a message to the configured chat. Returns message_id or None."""
    if not settings.TELEGRAM_BOT_TOKEN or not settings.TELEGRAM_CHAT_ID:
        log.warning("Telegram not configured — skipping send")
        return None

    payload = {
        "chat_id": settings.TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": parse_mode,
        "disable_web_page_preview": True,
    }

    try:
        with httpx.Client(timeout=10.0) as client:
            resp = client.post(_api_url("sendMessage"), json=payload)

        data = resp.json()
        if data.get("ok"):
            msg_id = data["result"]["message_id"]
            log.info("Telegram sent — message_id=%d", msg_id)
            return msg_id
        else:
            log.error("Telegram API error: %s", data.get("description"))
            return None

    except httpx.RequestError as exc:
        log.error("Telegram request failed: %s", exc)
        return None


def send_detector_offline_alert() -> None:
    send_message("⚠️ <b>Détecteur HORS LIGNE</b>\nAucun ping reçu depuis 5 minutes.")


def send_detector_online_alert() -> None:
    send_message("✅ <b>Détecteur EN LIGNE</b>\nConnexion rétablie.")
