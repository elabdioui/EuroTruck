# SPEC 0 — EuroTruck Shared Contracts

> **Status:** Foundational contract. MUST be loaded first in every Codex session,
> before any other SPEC. SPEC 0 produces **no code by itself** — it defines the
> contracts, conventions, and reuse boundaries that ALL subsequent specs (SPEC 1+)
> must conform to. Authored by Claude (pilot). Implemented progressively by Codex.

---

## 1. Project identity

- **Name:** EuroTruck
- **Origin:** hard fork of Magic (XAUUSD signal copilot) at tag `eurotruck-fork-point`.
- **Instrument:** EURUSD — symbol `EURUSDm` on Exness — replacing XAUUSD.
- **Role:** Telegram signal copilot. **SIGNAL ONLY, no auto-execution** (same as Magic).
  Human reviews each signal and enters manually.
- **New capability vs Magic:** autonomous **Signal Lifecycle Tracking** (virtual outcome
  monitoring) + a measurement dashboard.
- **North star for this phase:** make EURUSD setups *produce measurable signals with
  tracked outcomes*. **NOT profitability yet.** The goal is to build the 100+ tracked-signal
  sample that turns hypotheses into measured edge.

---

## 2. Non-negotiable principles

1. **Code correctness ≠ proven edge.** All win rates are pre-test hypotheses until a
   100+ tracked-signal sample exists.
2. **No silent rejection.** Every rejection path (every `return None`) MUST log its exact
   reason via the stats/log mechanism. Mandatory from day 1 — this is the failure mode
   we already know from Autonomus; do not reimport it.
3. **Measure first, redesign second.** No gate relaxation or architecture change before
   tracked data justifies it.
4. **Reuse over rewrite.** FROZEN modules (§4.A) are used as-is. Codex must not reimplement them.
5. **Gold preservation.** XAUUSD strategy modules stay in the repo, disabled — never deleted.
6. **Look-ahead safety.** The `find_swings` look-ahead fix (`confirmed_index` in
   `detector/indicators/structure.py`) MUST be verified intact and used by every consumer.

---

## 3. Session / killzone reorientation (EURUSD vs Magic)

- Magic is **NY-centric**. EuroTruck is **London-dominant**.
- **Primary killzone:** London (02:00–05:00 NY).
- **Secondary:** London/NY overlap (08:00–11:00 NY).
- **Asian range** remains the liquidity reference (sweep target), not an entry session.
- This is implemented in the killzone SPEC, not here — but **every setup assumes it**.

---

## 4. Reuse inventory (authoritative)

### 4.A — FROZEN (reuse as-is, do NOT modify or reimplement)
- `detector/indicators/`: `fvg.py`, `order_block.py`, `liquidity.py`, `structure.py`, `fibonacci.py`
- `detector/main.py` (scan loop, heartbeat), `detector/mt5_client.py`, `detector/stats.py` (SCAN_STATS)
- `detector/strategy/scoring.py`
- `backend/services/telegram/`: `client.py`, `formatter.py`
- `backend/services/llm/`: `groq.py`, `router.py`
- `backend/db/database.py` — **extend with new tables only** (see §5.1), do not break existing schema
- `backend/api/`: `health.py`, `logs.py`, `signal.py`
- `ops/` — `bot.ps1` and tooling
- `shared/models.py` — **extend**, never break existing fields

> If a FROZEN module appears to need a change, **STOP** and flag it for a SPEC 0 amendment.
> Do not edit it inside another spec.

### 4.B — RECALIBRATE (EURUSD-specific, via dedicated specs)
- `detector/config.py` — `PIP` (0.10 → EURUSD value), `SYMBOL` (`EURUSDm`), displacement /
  FVG min-size thresholds, SL/TP distances, `SIGNAL_TTL`, partial-TP constants.
- `detector/strategy/killzone.py` — NY → London dominant.
- `backend/services/news/` — `forex_factory.py` rescope (US/DXY red news → ECB/Fed/EUR);
  `dxy_yields.py` demoted (gold-specific, low relevance for EURUSD).

### 4.C — DISABLED (kept in repo for future use, removed from `ENABLED_TIERS`)
- `detector/strategy/`: `tier_s.py`, `tier_a.py`, `tier_b.py`, `tier_swing.py`, `orb.py`

### 4.D — NEW (to build via SPEC 1+)
- New strategy modules: `london_judas.py`, `ote_continuation.py`, `pdhpdl_sweep.py` (one per spec)
- **Signal Lifecycle Tracker** service (§5)
- **Measurement dashboard** + Excel/CSV export (§6)

---

## 5. Shared contracts

### 5.1 Signal schema — SQLite table `signal_lifecycle`
Every emitted signal is persisted with these fields (extends Magic's alert model):

| Field | Type | Notes |
|---|---|---|
| `id` | uuid | primary key |
| `created_at` | utc datetime | emission time |
| `setup` | enum | `london_judas` \| `ote_continuation` \| `pdhpdl_sweep` \| … |
| `direction` | enum | `LONG` \| `SHORT` |
| `session` | enum | `london` \| `overlap` \| `ny_am` \| … |
| `entry` | float | price |
| `sl` | float | price |
| `tp1` | float | partial target |
| `tp_final` | float | full target |
| `rr_planned` | float | planned reward:risk |
| `confluence_tags` | json | e.g. `["sweep_asian_high","choch_m5","fvg_m5","ote_0618"]` |
| `status` | enum | `OPEN` \| `TP1_HIT` \| `TP_FULL` \| `SL` \| `EXPIRED` |
| `outcome_r` | float \| null | realized R, null while OPEN |
| `mfe` | float | max favorable excursion (price) |
| `mae` | float | max adverse excursion (price) |
| `duration_sec` | int \| null | null while OPEN |
| `resolved_at` | utc \| null | null while OPEN |

### 5.2 Strategy interface (every setup conforms)
Every setup module exposes one entry function with a fixed signature:

```
def scan(ctx: MarketContext) -> Signal | None
```

- Returns a populated `Signal` (status=`OPEN`) on a valid setup, else `None`.
- On `None`: MUST call `stats.record(setup, reason)` with the exact rejection reason.
  **No silent None.**
- MUST NOT place orders. Signal-only.
- MUST read all thresholds from `config`, never hardcode instrument values.

### 5.3 Lifecycle tracker contract
A background job (APScheduler, existing) polls price for every `OPEN` signal and resolves it:

| Outcome | Condition | `outcome_r` |
|---|---|---|
| `SL` | price hits `sl` before any TP | `-1` |
| `TP1_HIT` | hits `tp1`, then returns to BE/SL before `tp_final` | partial model (§5.4) |
| `TP_FULL` | reaches `tp_final` | `rr_planned` |
| `EXPIRED` | `SIGNAL_TTL` elapsed with no resolution | mark-to-market in R |

- On **every** poll, update `mfe`, `mae`, `duration_sec`.

### 5.4 Partial-TP model (default — configurable, lives in `config`)
- 50% off at `tp1` (= +1R locked), SL → breakeven, runner to `tp_final`.
- `TP1_HIT` → `outcome_r = 0.5 * 1R + 0.5 * (BE = 0) = +0.5R` if runner stopped at BE.
- `TP_FULL` → `outcome_r = 0.5 * 1R + 0.5 * rr_planned`.
- Constants (`PARTIAL_TP_FRACTION`, etc.) are config values, **never hardcoded** in the tracker.

---

## 6. Measurement layer

- **Source of truth:** SQLite `signal_lifecycle`.
- **Dashboard:** served by the reused FastAPI backend. Per-setup live metrics:
  count, measured WR, realized avg RR, expectancy (R), frequency.
- **Export:** one-click Excel/CSV dump of `signal_lifecycle` for offline analysis.
- **No external dependencies** (no Google Sheets — auth/fragility avoided).

---

## 7. Conventions for Codex

- **One SPEC per session.** SPEC 0 loaded first, always.
- **Branch per spec:** `spec-N-<slug>` (e.g. `spec-1-config`). Commit, push, report branch name.
- **Do not modify FROZEN modules** (§4.A). Flag for SPEC 0 amendment instead.
- **Every new rejection path logs a reason.** Verified in review.
- **English** code and comments. **Match Magic's existing module/function naming.**
- **No new heavy dependencies** without flagging first.

---

## 8. Spec sequence (roadmap)

| SPEC | Title | Owner | Produces code? |
|---|---|---|---|
| 0 | Shared contracts (this doc) | Claude | No |
| 1 | Config recalibration (EURUSD constants) | Codex | Yes |
| 2 | Killzone reorientation (London dominant) | Codex | Yes |
| 3 | Signal Lifecycle Tracker + schema | Codex | Yes |
| 4 | Setup #1 — London Judas Swing | Codex | Yes |
| 5 | Dashboard + Excel/CSV export | Codex | Yes |
| 6 | Setup #2 — OTE Continuation | Codex | Yes |
| 7 | Setup #3 — PDH/PDL Sweep | Codex | Yes |

> Tracker (SPEC 3) lands **before** the first setup (SPEC 4) so the very first emitted
> signal is measured. Dashboard (SPEC 5) follows once signals exist to display.

---

*End of SPEC 0. Amendments require an explicit version bump and re-load in subsequent sessions.*