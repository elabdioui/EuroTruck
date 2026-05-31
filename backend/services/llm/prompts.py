"""LLM prompt templates."""
import json


SYSTEM_PROMPT = """Tu es un analyste XAUUSD scalping ICT expert.
Tu APPLIQUES STRICTEMENT les règles suivantes :
- JAMAIS de scalp si news rouge US dans ±15min (NFP, CPI, FOMC, etc.)
- Le biais H4 et H1 DOIVENT être alignés
- Sessions autorisées : London, NY AM, NY PM uniquement
- Tu réponds UNIQUEMENT en JSON valide, sans markdown, sans commentaires

RÈGLES DE DÉCISION (priorité décroissante) :
1. Si ALERTE NEWS ROUGE = OUI → verdict OBLIGATOIREMENT "NO_GO".
2. Si MACRO ALIGNMENT = CONTRADICT et score signal < 6 → "WAIT" ou "NO_GO".
3. Si MACRO ALIGNMENT = CONFIRM, biais H4/H1 alignés et score >= 7 → "GO" raisonnable.
4. Sinon, juge au cas par cas ; en cas de doute, préfère "WAIT".
Remplis toujours risk_main avec le risque le plus important (macro contradictoire,
événement imminent dans la fenêtre, ou structure fragile)."""


def build_user_prompt(signal: dict, news_context: dict) -> str:
    upcoming = news_context.get("upcoming_us_events", [])
    red_imminent = news_context.get("red_news_imminent", False)
    macro_str = news_context.get("macro", "")
    macro_align = news_context.get("macro_alignment")  # may be absent

    news_window_str = json.dumps(upcoming, ensure_ascii=False, indent=2) if upcoming else "Aucun événement US imminent"

    # Macro alignment section (only when provided by the aggregator).
    if macro_align:
        macro_align_str = (
            f"\nMACRO ALIGNMENT : {macro_align.get('macro_alignment', 'UNKNOWN')}\n"
            f"{macro_align.get('detail', '')}\n"
        )
    else:
        macro_align_str = ""

    return f"""SIGNAL DÉTECTÉ :
{json.dumps(signal, ensure_ascii=False, indent=2)}

NEWS US (60 prochaines minutes) :
{news_window_str}

ALERTE NEWS ROUGE : {"OUI ⚠️ — BLOQUE AUTOMATIQUEMENT" if red_imminent else "NON"}
{macro_align_str}
CONTEXTE MACRO (24H) :
{macro_str}

RÉPONDS EN JSON STRICT (pas de markdown, pas de texte avant/après) :
{{
  "verdict": "GO" ou "NO_GO" ou "WAIT",
  "reason_short": "1 phrase max 20 mots (référence le macro alignment si pertinent)",
  "risk_main": "1 risque principal à surveiller",
  "action": "action immédiate concrète pour le trader"
}}"""