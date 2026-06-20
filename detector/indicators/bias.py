"""Trend-bias indicator helpers."""

import pandas as pd


def ema(values: pd.Series, period: int) -> pd.Series:
    """Return an exponential moving average using the standard span formula."""
    return pd.to_numeric(values, errors="coerce").ewm(
        span=period, adjust=False, min_periods=period
    ).mean()
