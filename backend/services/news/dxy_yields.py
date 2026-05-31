"""DXY and US 10Y Yield snapshots via yfinance, plus macro alignment vs a signal."""
import logging
from dataclasses import dataclass

import yfinance as yf

log = logging.getLogger(__name__)


@dataclass
class MacroContext:
    dxy_price: float
    dxy_change_1h_pct: float
    dxy_change_24h_pct: float

    yield_10y: float
    yield_change_1h_bp: float    # basis points
    yield_change_24h_bp: float

    @property
    def dxy_trend(self) -> str:
        if self.dxy_change_24h_pct > 0.3:
            return "STRONG_UP"
        if self.dxy_change_24h_pct > 0.1:
            return "UP"
        if self.dxy_change_24h_pct < -0.3:
            return "STRONG_DOWN"
        if self.dxy_change_24h_pct < -0.1:
            return "DOWN"
        return "FLAT"

    @property
    def xauusd_implication(self) -> str:
        """DXY inverse relationship with gold."""
        if self.dxy_trend in ("STRONG_UP", "UP"):
            return "Bearish gold (DXY rising)"
        if self.dxy_trend in ("STRONG_DOWN", "DOWN"):
            return "Bullish gold (DXY falling)"
        return "Neutral macro"

    def to_prompt_string(self) -> str:
        return (
            f"DXY {self.dxy_price:.2f} ({self.dxy_change_24h_pct:+.2f}% 24h) — {self.dxy_trend}\n"
            f"US 10Y Yield {self.yield_10y:.3f}% ({self.yield_change_24h_bp:+.1f}bp 24h)\n"
            f"Macro implication: {self.xauusd_implication}"
        )


def macro_alignment(direction: str, macro: MacroContext | None) -> dict:
    """
    Decide whether DXY + 10Y yields CONFIRM, CONTRADICT, or are NEUTRAL to a gold
    signal. Gold is inversely correlated to DXY.

    Returns {"macro_alignment": "CONFIRM"|"CONTRADICT"|"NEUTRAL"|"UNKNOWN",
             "detail": str}
    """
    if macro is None:
        return {"macro_alignment": "UNKNOWN", "detail": "Macro data unavailable"}

    trend = macro.dxy_trend

    if direction == "LONG":
        if trend in ("STRONG_DOWN", "DOWN"):
            verdict = "CONFIRM"
            detail = f"DXY falling ({macro.dxy_change_24h_pct:+.2f}% 24h) — bullish for gold"
        elif trend in ("STRONG_UP", "UP"):
            verdict = "CONTRADICT"
            detail = f"DXY rising ({macro.dxy_change_24h_pct:+.2f}% 24h) — bearish pressure on gold"
        else:
            verdict = "NEUTRAL"
            detail = "DXY flat — no macro edge"
    else:  # SHORT
        if trend in ("STRONG_UP", "UP"):
            verdict = "CONFIRM"
            detail = f"DXY rising ({macro.dxy_change_24h_pct:+.2f}% 24h) — bearish for gold"
        elif trend in ("STRONG_DOWN", "DOWN"):
            verdict = "CONTRADICT"
            detail = f"DXY falling ({macro.dxy_change_24h_pct:+.2f}% 24h) — bullish pressure on gold"
        else:
            verdict = "NEUTRAL"
            detail = "DXY flat — no macro edge"

    # Refine with 10Y yields: rising yields align with rising DXY (bearish gold).
    # If yields disagree with the DXY-based CONFIRM, downgrade to NEUTRAL.
    if verdict == "CONFIRM":
        if direction == "LONG" and macro.yield_change_24h_bp > 3:
            verdict = "NEUTRAL"
            detail += " (but 10Y yields rising — partial contradiction)"
        elif direction == "SHORT" and macro.yield_change_24h_bp < -3:
            verdict = "NEUTRAL"
            detail += " (but 10Y yields falling — partial contradiction)"

    return {"macro_alignment": verdict, "detail": detail}


def fetch_macro() -> MacroContext | None:
    try:
        dxy = yf.Ticker("DX-Y.NYB")
        dxy_hist = dxy.history(period="2d", interval="1h")
        if dxy_hist.empty:
            raise ValueError("Empty DXY data")

        dxy_now = float(dxy_hist["Close"].iloc[-1])
        dxy_1h_ago = float(dxy_hist["Close"].iloc[-2]) if len(dxy_hist) >= 2 else dxy_now
        dxy_24h_ago = float(dxy_hist["Close"].iloc[-25]) if len(dxy_hist) >= 25 else dxy_now

        dxy_1h_chg = (dxy_now - dxy_1h_ago) / dxy_1h_ago * 100
        dxy_24h_chg = (dxy_now - dxy_24h_ago) / dxy_24h_ago * 100

        tnx = yf.Ticker("^TNX")
        tnx_hist = tnx.history(period="2d", interval="1h")
        if tnx_hist.empty:
            raise ValueError("Empty TNX data")

        y_now = float(tnx_hist["Close"].iloc[-1])
        y_1h_ago = float(tnx_hist["Close"].iloc[-2]) if len(tnx_hist) >= 2 else y_now
        y_24h_ago = float(tnx_hist["Close"].iloc[-25]) if len(tnx_hist) >= 25 else y_now

        return MacroContext(
            dxy_price=dxy_now,
            dxy_change_1h_pct=dxy_1h_chg,
            dxy_change_24h_pct=dxy_24h_chg,
            yield_10y=y_now,
            yield_change_1h_bp=(y_now - y_1h_ago) * 100,
            yield_change_24h_bp=(y_now - y_24h_ago) * 100,
        )

    except Exception as exc:
        log.error("Macro fetch failed: %s", exc)
        return None