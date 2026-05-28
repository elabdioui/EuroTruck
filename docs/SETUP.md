# Guide d'installation

## Prérequis
- Windows 10/11 avec MetaTrader 5 installé et connecté à ton broker
- Python 3.11+
- Compte Railway ou Render (gratuit)
- Clés API : Gemini (Google AI Studio), Groq Cloud, Telegram Bot

---

## Nœud 1 — Détecteur (PC Windows)

```bash
cd detector
pip install -r requirements.txt
copy .env.example .env
# Édite .env avec tes credentials MT5 et l'URL du backend
python main.py
```

Pour lancer automatiquement au démarrage Windows (Task Scheduler) :
- Action : `python C:\...\detector\main.py`
- Trigger : "Au démarrage de session"
- Travailler dans le répertoire : `C:\...\detector`

---

## Nœud 2 — Backend (Railway)

1. Push le repo sur GitHub
2. Railway → New Project → Deploy from GitHub
3. Sélectionne le repo, Railway détecte le `Dockerfile`
4. Ajoute toutes les variables d'env (copie `.env.example`)
5. Deploy → URL Railway disponible (ex: `https://xauusd-bot.up.railway.app`)
6. Met à jour `BACKEND_WEBHOOK_URL` dans le `.env` du détecteur

### Uptime-robot (anti-hibernation gratuit)
- uptime-robot.com → Add Monitor → HTTP(S)
- URL : `https://ton-app.railway.app/health`
- Interval : 5 minutes

---

## Tests

```bash
# Backend (depuis la racine du projet)
cd ..
pip install pytest
pytest tests/test_backend.py -v

# Détecteur (sans MT5)
pytest tests/test_detector.py -v
```

---

## Test bout en bout (signal mocké)

```bash
python tests/send_mock_signal.py
```

Ce script envoie un faux signal Tier S au backend pour tester la chaîne complète.
