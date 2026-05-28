"""DXY and US 10Y Yield snapshots via yfinance."""
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
