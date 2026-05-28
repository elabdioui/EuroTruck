"""Groq Llama — fallback LLM client."""
import json
import logging

from groq import Groq

from core.config import settings

log = logging.getLogger(__name__)
_groq_client: Groq | None = None


def _get_client() -> Groq:
    global _groq_client
    if _groq_client is None:
        _groq_client = Groq(api_key=settings.GROQ_API_KEY)
    return _groq_client


def call_groq(system_prompt: str, user_prompt: str) -> dict | None:
    """Returns parsed JSON dict from Groq, or None on failure."""
    if not settings.GROQ_API_KEY:
        log.warning("GROQ_API_KEY not set")
        return None

    try:
        client = _get_client()
        completion = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.1,
            max_tokens=256,
            response_format={"type": "json_object"},
        )
        text = completion.choices[0].message.content or ""
        return json.loads(text)

    except json.JSONDecodeError as exc:
        log.warning("Groq JSON parse error: %s", exc)
        return None
    except Exception as exc:
        log.error("Groq call failed: %s", exc)
        return None
