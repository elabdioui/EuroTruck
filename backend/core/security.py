"""HMAC webhook verification and API token auth."""
import hashlib
import hmac
import json
import logging

from fastapi import HTTPException, Request, Header

from core.config import settings

log = logging.getLogger(__name__)


def verify_hmac(payload: bytes, signature: str) -> bool:
    expected = hmac.new(
        settings.WEBHOOK_HMAC_SECRET.encode(),
        payload,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


async def require_hmac(request: Request) -> bytes:
    """FastAPI dependency: validates HMAC and returns raw body bytes."""
    body = await request.body()
    sig = request.headers.get("X-HMAC-Signature", "")

    if not settings.WEBHOOK_HMAC_SECRET:
        log.warning("WEBHOOK_HMAC_SECRET not set — skipping HMAC check")
        return body

    if not sig or not verify_hmac(body, sig):
        log.warning("Invalid HMAC from %s", request.client)
        raise HTTPException(status_code=401, detail="Invalid HMAC signature")

    return body


def require_api_token(authorization: str = Header(...)) -> None:
    """FastAPI dependency: validates Bearer token for read endpoints."""
    if not settings.API_SECRET_TOKEN:
        return
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or token != settings.API_SECRET_TOKEN:
        raise HTTPException(status_code=403, detail="Invalid API token")
