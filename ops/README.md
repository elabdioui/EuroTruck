# Operations Guide — eurotruck-bot

All commands are run from the repo root or any directory:

```powershell
.\ops\bot.ps1 <command>
```

---

## Daily routine

```powershell
.\ops\bot.ps1 status
```

Run this every morning instead of manually checking logs. Exit code 0 = all green.
It shows: backend service state, detector liveness (ALIVE if log < 15 min old), git HEAD,
MT5 process presence, and active session ID.

---

## Updating the bot

```powershell
.\ops\bot.ps1 update
```

Runs the full update sequence automatically:
1. `git pull` — aborts with a clear message on merge conflict
2. Restarts the detector (always)
3. Restarts the backend service only if `backend/` files changed
4. Waits 15 s, tails last 5 detector log lines, runs `status`

Downtime < 30 s. Use `-All` to force backend restart even without backend/ changes.

---

## Viewing logs

```powershell
.\ops\bot.ps1 logs              # tail -30 detector-wrapper.log
.\ops\bot.ps1 logs backend      # tail -30 backend.log
.\ops\bot.ps1 logs stats        # filter SCAN_STATS lines from detector log
```

Add `-Wait` to keep tailing: `.\ops\bot.ps1 logs -Wait`

---

## Safe RDP disconnect

> **WARNING: Never close the RDP window with the X button.**
> Closing RDP normally suspends the session — MT5 loses IPC and the detector stops working.

Always disconnect with:

```powershell
.\ops\bot.ps1 disconnect
```

This runs `tscon <sessionId> /dest:console`, which keeps the session **Active** so MT5
retains its IPC connection. The desktop shortcut **Deconnexion Safe** on the bot VM does
the same thing.

---

## Other commands

```powershell
.\ops\bot.ps1 start             # start backend + detector, wait 15 s, show status
.\ops\bot.ps1 stop              # stop detector python (matched by cmd line) + backend service
.\ops\bot.ps1 restart           # restart detector only
.\ops\bot.ps1 restart -All      # restart detector + backend
```

---

## Full VM migration checklist

Use this when moving the bot to a new Windows VM.

### Prerequisites (manual, before running install.ps1)

1. **Clone the repo**
   ```powershell
   git clone <repo-url> C:\Bot\eurotruck-bot
   ```

2. **Install MT5**
   - Download and install MetaTrader 5
   - Log in to your broker account at least once (creates the AppData profile)

3. **Copy `.env`**
   - Copy your existing `.env` from the old VM to the repo root
   - Verify all keys are present (`MT5_LOGIN`, `MT5_PASSWORD`, `MT5_SERVER`, `BACKEND_URL`, etc.)

4. **Install Python 3.12+** and ensure `python` is on PATH

5. **Place `nssm.exe`** in `ops\bin\nssm.exe`
   - Download from https://nssm.cc (offline VPS-safe — no auto-download)

### Install (run as Administrator)

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\ops\install.ps1
```

The script is idempotent — safe to re-run. It:
- Checks preflight (Python, git, .env)
- Creates `.venv` and installs dependencies
- Discovers `terminal64.exe` and writes `MT5_PATH` to `.env`
- Registers NSSM service `eurotruck-backend`
- Registers Task Scheduler task `eurotruck-detector` (AtLogOn, interactive session)
- Creates desktop shortcuts (Bot Status, Deconnexion Safe)
- Prints autologon instructions

### After install

```powershell
.\ops\bot.ps1 status
```

If detector shows DEAD — trigger it manually for this session:
```powershell
.\ops\bot.ps1 start
```

### Configure autologon (for unattended reboots)

The detector needs an interactive session after every reboot. Configure Windows auto-logon:
1. Download [Sysinternals Autologon](https://learn.microsoft.com/sysinternals/downloads/autologon)
2. Run as Administrator → enter bot user credentials → Enable

Without this, the detector will not restart automatically after a reboot.

---

## Architecture constraints

These are intentional and must not be changed without understanding the implications:

| Component | How it runs | Why |
|-----------|-------------|-----|
| Backend (FastAPI) | Windows service via NSSM | Survives logoffs; session 0 is fine for HTTP |
| Detector | Task Scheduler AtLogOn → `start_detector.bat` | MT5 IPC **fails** in session 0; needs interactive session |
| RDP disconnect | `tscon <id> /dest:console` | Closing RDP window suspends session, killing MT5 IPC |
| Logs | `backend-error.log` (uvicorn stdout), `backend.log` (app), `detector-wrapper.log` | Fixed layout expected by `bot.ps1 logs` |
