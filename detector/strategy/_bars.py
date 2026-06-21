"""Shared candle-state helpers for strategy scanners."""

import pandas as pd


def closed(frame: pd.DataFrame) -> pd.DataFrame:
    """Drop the still-forming final candle returned by MT5."""
    return frame.iloc[:-1]
