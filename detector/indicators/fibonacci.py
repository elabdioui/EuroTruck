"""Fibonacci retracement levels and OTE zone computation."""
from dataclasses import dataclass


@dataclass
class FibLevels:
    swing_high: float
    swing_low: float
    direction: str      # "BULLISH" (retracing down) | "BEARISH" (retracing up)

    @property
    def range(self) -> float:
        return self.swing_high - self.swing_low

    def level(self, ratio: float) -> float:
        if self.direction == "BULLISH":
            return self.swing_high - self.range * ratio
        return self.swing_low + self.range * ratio

    @property
    def ote_low(self) -> float:
        return self.level(0.786) if self.direction == "BULLISH" else self.level(0.618)

    @property
    def ote_high(self) -> float:
        return self.level(0.618) if self.direction == "BULLISH" else self.level(0.786)

    @property
    def equilibrium(self) -> float:
        return self.level(0.500)

    def is_in_ote(self, price: float) -> bool:
        lo = min(self.ote_low, self.ote_high)
        hi = max(self.ote_low, self.ote_high)
        return lo <= price <= hi

    def is_in_discount(self, price: float) -> bool:
        """Below 0.5 for bullish move (discounted prices)."""
        if self.direction == "BULLISH":
            return price <= self.equilibrium
        return price >= self.equilibrium


def compute_fib_from_sweep(sweep_low: float, swing_high: float) -> FibLevels:
    """Build fib for a bullish setup: sweep SSL (low) → targeting swing high."""
    return FibLevels(swing_high=swing_high, swing_low=sweep_low, direction="BULLISH")


def compute_fib_from_sweep_bearish(sweep_high: float, swing_low: float) -> FibLevels:
    """Build fib for a bearish setup: sweep BSL (high) → targeting swing low."""
    return FibLevels(swing_high=sweep_high, swing_low=swing_low, direction="BEARISH")
