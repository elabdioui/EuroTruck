# SPEC 0 — AMENDMENT v1.1

> **Load alongside SPEC 0 and SPEC 1.** This amendment bumps SPEC 0 to **v1.1** and grants
> bounded authorization for the frozen-module edits SPEC 1 requires. It also patches SPEC 1
> to fix a second gold-hardcoded landmine discovered during implementation.
> Authored by Claude (pilot) in response to Codex's two correct blockers.

---

## A. Why this amendment exists

Codex correctly refused to touch frozen modules without authorization. Two real conflicts:

1. **PIP must be resolved at runtime**, after MT5 connection — which lives in the frozen
   `mt5_client.py`. There is no non-frozen place to do this (config loads at import, before MT5).
2. **`order_block.py:40` has `body < 0.10  # ignore doji`** — a doji filter expressed in **price**.
   On gold, `0.10` = 1 pip (fine). On EURUSD, `0.10` = **1000 pips**, so every candle is treated
   as a doji and skipped → **zero Order Blocks ever detected**. The proposed `0.10`→`0.1`
   cosmetic change is **rejected**: it dodges the grep without fixing the broken detection.

Both are the same surgical family as the FVG/liquidity fix: replace a gold-hardcoded literal
with a `Config.PIP`-relative value, or add a bounded startup hook. **No detection logic changes.**

---

## B. Authorized frozen-module edits (extends SPEC 0 §4.A)

The following edits to FROZEN modules are **explicitly authorized for SPEC 1 only**. They are
constant-substitution or additive-hook edits. Detection/connection **logic must remain unchanged**.

| File | Edit | Constraint |
|---|---|---|
| `detector/indicators/fvg.py` | `pip_unit = 0.10` → `Config.PIP`; update stale comment | already in SPEC 1 §2.2 |
| `detector/indicators/liquidity.py` | `pip_unit = 0.10` (both sites) → `Config.PIP` | already in SPEC 1 §2.2 |
| `detector/indicators/order_block.py` | `body < 0.10` → `body < Config.OB_MIN_BODY_PIPS * Config.PIP` | **NEW**; comment stays `# ignore doji`; nothing else changes |
| `detector/mt5_client.py` | **additive** PIP resolution + log, after successful connection | **NEW**; must not alter connect / retry / existing returns |

**Authorized `mt5_client.py` hook (shape, not literal text):** after the symbol is confirmed
available post-connection, resolve and log PIP, then return as before:

```python
info = mt5.symbol_info(Config.SYMBOL)
override = float(os.getenv("PIP_OVERRIDE") or 0)
Config.PIP = override if override > 0 else info.point * 10
log.info("pip_resolved symbol=%s pip=%s", Config.SYMBOL, Config.PIP)
```

Any frozen change beyond these four rows still requires STOP + flag (SPEC 0 §4.A unchanged otherwise).

---

## C. SPEC 1 patch (deltas to apply)

**C.1 — New config constant** (`detector/config.py`):
```
OB_MIN_BODY_PIPS: float = 1.0   # doji filter; mirrors gold's 1-pip intent. Starting hypothesis.
```

**C.2 — `Config.PIP` default** (`detector/config.py`): declare `PIP: float = 0.0001` as a safe
default (EURUSD), **overwritten at startup** by the `mt5_client.py` hook (§B). Never left unset.

**C.3 — PIP resolution location:** in `mt5_client.py` post-connection (§B), **not** at config import.

**C.4 — Corrected AC2** (replaces SPEC 1 §4 AC2):
> `grep -rnE "0\.10|< 0\.1[^0-9]" detector/indicators/` returns **nothing in code lines** once
> all THREE indicator literals are converted (`fvg.py`, `liquidity.py`, `order_block.py`).
> This is now satisfiable legitimately — **no cosmetic `0.10`→`0.1` edits permitted.**

**C.5 — New AC9 (OB doji sanity):**
> With `PIP = 0.0001` and `OB_MIN_BODY_PIPS = 1.0`, the doji threshold is `0.0001`, so normal
> EURUSD M5 candles (body ≫ 1 pip) are **not** filtered as doji. Codex confirms via the existing
> OB test fixture (or a minimal one) that `detect_order_blocks` returns ≥ 1 OB on a sample where
> it previously returned 0 under the gold threshold.

**C.6 — AC3 extended:** the "logic byte-for-byte unchanged except substitution" rule now also
covers `order_block.py` (only the threshold line changes) and `mt5_client.py` (only the additive
hook is added; existing lines untouched).

---

## D. Net effect

After SPEC 1 (as amended): the engine resolves PIP from the live symbol, all three frozen
indicators are instrument-correct, gold tiers are disabled, and the detector boots on `EURUSDm`
with FVG, liquidity, **and** Order Block detection all functional — ready for the tracker (SPEC 3)
and first setup (SPEC 4). Still no signal expected until a setup is enabled.

---

*SPEC 0 is now v1.1. Subsequent sessions load SPEC 0 + this amendment.*
