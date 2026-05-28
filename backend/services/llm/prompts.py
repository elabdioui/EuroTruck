"""LLM prompt templates."""
import json


SYSTEM_PROMPT = """Tu es un analyste XAUUSD scalping ICT expert.
Tu APPLIQUES STRICTEMENT les règles suivantes :
- JAMAIS de scalp si news rouge US dans ±15min (NFP, CPI, FOMC, etc.)
- Le biais H4 et H1 DOIVENT être alignés
- Sessions autorisées : London, NY AM, NY PM uniquement
- Tu réponds UNIQUEMENT en JSON valide, sans markdown, sans commentaires"""


def build_user_prompt(signal: dict, news_context: dict) -> str:
    upcoming = news_context.get("upcoming_us_events", [])
    red_imminent = news_context.get("red_news_imminent", False)
    macro_str = news_context.get("macro", "")

    news_window_str = json.dumps(upcoming, ensure_ascii=False, indent=2) if upcoming else "Aucun événement US imminent"

    return f"""SIGNAL DÉTECTÉ :
{json.dumps(signal, ensure_ascii=False, indent=2)}

NEWS US (60 prochaines minutes) :
{news_window_str}

ALERTE NEWS ROUGE : {"OUI ⚠️ — BLOQUE AUTOMATIQUEMENT" if red_imminent else "NON"}

CONTEXTE MACRO (24H) :
{macro_str}

RÉPONDS EN JSON STRICT (pas de markdown, pas de texte avant/après) :
{{
  "verdict": "GO" ou "NO_GO" ou "WAIT",
  "reason_short": "1 phrase max 20 mots",
  "risk_main": "1 risque principal à surveiller",
  "action": "action immédiate concrète pour le trader"
}}"""
