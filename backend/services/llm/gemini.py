"""Gemini 2.0 Flash — primary LLM client."""
import json
import logging

from google import genai
from google.genai import types

from core.config import settings

log = logging.getLogger(__name__)

_client: genai.Client | None = None


def _get_client() -> genai.Client:
    global _client
    if _client is None:
        _client = genai.Client(api_key=settings.GEMINI_API_KEY)
    return _client


def call_gemini(system_prompt: str, user_prompt: str) -> dict | None:
    """Returns parsed JSON dict from Gemini, or None on failure."""
    if not settings.GEMINI_API_KEY:
        log.warning("GEMINI_API_KEY not set")
        return None

    try:
        client = _get_client()
        response = client.models.generate_content(
            model="gemini-2.0-flash",
            contents=user_prompt,
            config=types.GenerateContentConfig(
                system_instruction=system_prompt,
                temperature=0.1,
                max_output_tokens=256,
            ),
        )
        text = response.text.strip()
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
        return json.loads(text)

    except json.JSONDecodeError as exc:
        log.warning("Gemini JSON parse error: %s", exc)
        return None
    except Exception as exc:
        log.error("Gemini call failed: %s", exc)
        return None
