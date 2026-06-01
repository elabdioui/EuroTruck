"""
Envoie un signal mock signé au backend pour tester le pipeline complet.

Usage:
  python tests/send_mock_signal.py                     → Tier S LONG (défaut)
  python tests/send_mock_signal.py --tier A            → Tier A LONG
  python tests/send_mock_signal.py --tier B --dir SHORT
  python tests/send_mock_signal.py --tier S --dir SHORT
  python tests/send_mock_signal.py --list              → affiche tous les presets
"""
import argparse
import hashlib
import hmac
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
import httpx

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

BACKEND_URL = os.getenv("BACKEND_WEBHOOK_URL", "http://localhost:8000/signal")
SECRET = os.getenv("WEBHOOK_HMAC_SECRET", "")
if not SECRET:
    sys.exit("WEBHOOK_HMAC_SECRET is not set — vérifiez votre .env")

_NOW = datetime.now(tz=timezone.utc).isoformat()

PRESETS: dict[str, dict] = {
    "S_LONG": {
        "tier": "S", "direction": "LONG",
        "pattern": "Golden Setup", "killzone": "NY_AM",
        "entry_zone_low": 3310.50, "entry_zone_high": 3312.00,
        "stop_loss": 3302.00, "take_profit": 3340.00,
        "bias_h4": "BULLISH", "bias_h1": "BULLISH",
        "confluences": ["Bias_H4", "Bias_H1", "SSL_Sweep", "CHoCH_M5", "FVG_M5", "OTE_0.618"],
        "confluence_score": 9, "estimated_winrate": 0.72,
    },
    "S_SHORT": {
        "tier": "S", "direction": "SHORT",
        "pattern": "Golden Setup", "killzone": "LONDON",
        "entry_zone_low": 3318.00, "entry_zone_high": 3320.50,
        "stop_loss": 3328.00, "take_profit": 3295.00,
        "bias_h4": "BEARISH", "bias_h1": "BEARISH",
        "confluences": ["Bias_H4", "Bias_H1", "BSL_Sweep", "CHoCH_M5", "OB_M5", "OTE_0.786"],
        "confluence_score": 8, "estimated_winrate": 0.72,
    },
    "A_LONG": {
        "tier": "A", "direction": "LONG",
        "pattern": "OB Retest H1", "killzone": "NY_AM",
        "entry_zone_low": 3305.00, "entry_zone_high": 3308.00,
        "stop_loss": 3300.00, "take_profit": 3328.00,
        "bias_h4": "BULLISH", "bias_h1": "BULLISH",
        "confluences": ["Bias_H4", "OB_H1", "FVG_M5"],
        "confluence_score": 6, "estimated_winrate": 0.62,
    },
    "A_SHORT": {
        "tier": "A", "direction": "SHORT",
        "pattern": "London Open Sweep", "killzone": "LONDON",
        "entry_zone_low": 3322.00, "entry_zone_high": 3324.50,
        "stop_loss": 3330.00, "take_profit": 3305.00,
        "bias_h4": "BEARISH", "bias_h1": "BEARISH",
        "confluences": ["Bias_H4", "Asia_Sweep", "FVG_M5"],
        "confluence_score": 6, "estimated_winrate": 0.60,
    },
    "B_LONG": {
        "tier": "B", "direction": "LONG",
        "pattern": "Breaker + OTE", "killzone": "NY_AM",
        "entry_zone_low": 3308.00, "entry_zone_high": 3310.00,
        "stop_loss": 3303.50, "take_profit": 3325.00,
        "bias_h4": "BULLISH", "bias_h1": "BULLISH",
        "confluences": ["Bias_H4", "Breaker_M5", "OTE_0.618"],
        "confluence_score": 6, "estimated_winrate": 0.52,
    },
    "B_SHORT": {
        "tier": "B", "direction": "SHORT",
        "pattern": "BOS + FVG Retest", "killzone": "LONDON",
        "entry_zone_low": 3316.00, "entry_zone_high": 3318.00,
        "stop_loss": 3323.00, "take_profit": 3300.00,
        "bias_h4": "BEARISH", "bias_h1": "BEARISH",
        "confluences": ["Bias_H4", "BOS_M5", "FVG_M5"],
        "confluence_score": 6, "estimated_winrate": 0.50,
    },
}


def send(signal: dict) -> None:
    signal = {
        "id": f"mock-{signal['tier']}-{signal['direction']}-{datetime.now(tz=timezone.utc).strftime('%H%M%S')}",
        "timestamp": _NOW,
        "symbol": "XAUUSDm",
        **signal,
    }
    payload_bytes = json.dumps(signal, default=str, sort_keys=True).encode()
    sig = hmac.new(SECRET.encode(), payload_bytes, hashlib.sha256).hexdigest()
    headers = {"Content-Type": "application/json", "X-HMAC-Signature": sig}

    name = f"Tier {signal['tier']} {signal['direction']} — {signal['pattern']}"
    print(f"\n[>>] Envoi : {name}")
    print(f"     URL    : {BACKEND_URL}")
    try:
        resp = httpx.post(BACKEND_URL, content=payload_bytes, headers=headers, timeout=20.0)
        print(f"     Status : {resp.status_code}")
        try:
            data = resp.json()
            print(f"     Verdict: {data.get('verdict', '?')}  |  provider: {data.get('provider', '?')}")
            print(f"     TG sent: {data.get('telegram_sent', '?')}")
        except Exception:
            print(f"     Body   : {resp.text[:300]}")
    except httpx.RequestError as exc:
        print(f"     ERREUR : {exc}")
        sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(description="Envoie un mock signal au backend")
    parser.add_argument("--tier", choices=["S", "A", "B"], default="S")
    parser.add_argument("--dir",  choices=["LONG", "SHORT"], default="LONG")
    parser.add_argument("--all",  action="store_true", help="Envoie tous les presets")
    parser.add_argument("--list", action="store_true", help="Liste les presets disponibles")
    args = parser.parse_args()

    if args.list:
        print("Presets disponibles :")
        for key, p in PRESETS.items():
            print(f"  {key:10s} → {p['pattern']} ({p['killzone']})")
        return

    if args.all:
        for key, preset in PRESETS.items():
            send(preset)
        return

    key = f"{args.tier}_{args.dir}"
    if key not in PRESETS:
        sys.exit(f"Preset '{key}' introuvable. Utilisez --list pour voir les options.")
    send(PRESETS[key])


if __name__ == "__main__":
    main()
