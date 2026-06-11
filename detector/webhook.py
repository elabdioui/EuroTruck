"""HMAC-signed webhook client to POST signals to the backend."""
import hashlib
import hmac
import json
import logging

import httpx
import requests

from config import cfg

log = logging.getLogger(__name__)


def _sign(payload_bytes: bytes, secret: str) -> str:
    return hmac.new(secret.encode(), payload_bytes, hashlib.sha256).hexdigest()


def send_signal(signal_dict: dict) -> bool:
    """
    Serialize the signal dict to JSON (sort_keys=True for deterministic encoding),
    sign the exact bytes, and POST those exact bytes to the backend.
    The signature is transported only via X-HMAC-Signature header — never mutated
    into signal_dict so the signed bytes == the sent bytes.
    """
    payload_bytes = json.dumps(signal_dict, default=str, sort_keys=True).encode()
    signature = _sign(payload_bytes, cfg.WEBHOOK_HMAC_SECRET)

    headers = {
        "Content-Type": "application/json",
        "X-HMAC-Signature": signature,
    }

    try:
        with httpx.Client(timeout=10.0) as client:
            resp = client.post(cfg.BACKEND_WEBHOOK_URL, content=payload_bytes, headers=headers)
        if resp.is_success:
            log.info("Signal sent OK — tier=%s dir=%s score=%s",
                     signal_dict.get("tier"), signal_dict.get("direction"),
                     signal_dict.get("confluence_score"))
            _log_signal_to_sheet(signal_dict)
            return True
        else:
            log.warning("Backend returned %d: %s", resp.status_code, resp.text[:200])
            return False
    except httpx.RequestError as exc:
        log.error("Webhook request failed: %s", exc)
        return False


def _log_signal_to_sheet(signal: dict) -> None:
    if not cfg.SHEETS_WEBHOOK_URL:
        return
    payload = {
        "token": cfg.SHEETS_WEBHOOK_TOKEN,
        "nom_signal": signal.get("pattern"),
        "tier": signal.get("tier"),
        "date": signal.get("timestamp_maroc", ""),
        "heure": signal.get("timestamp_maroc", ""),
        "session": signal.get("killzone"),
        "direction": signal.get("direction"),
        "entry": f'{signal.get("entry_low")}-{signal.get("entry_high")}',
        "sl": signal.get("sl"),
        "tp": signal.get("tp"),
        "signal_id": signal.get("signal_id"),
    }
    # Format date/heure if timestamp_maroc is a datetime object
    ts = signal.get("timestamp_maroc")
    if hasattr(ts, "strftime"):
        payload["date"] = ts.strftime("%Y-%m-%d")
        payload["heure"] = ts.strftime("%H:%M")
    try:
        requests.post(cfg.SHEETS_WEBHOOK_URL, json=payload, timeout=4)
    except Exception as exc:
        log.warning("Sheet append failed (signal sent OK anyway): %s", exc)
