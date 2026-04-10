"""
strategy/swings.py — Swing high / swing low detection.

A swing high at bar i: high[i] is the maximum within [i-n, i+n].
A swing low  at bar i: low[i]  is the minimum within [i-n, i+n].

The `n` parameter controls sensitivity:
  - Larger n → fewer, more significant pivots
  - Smaller n → more pivots, noisier

Recommended values (from config):
  SWING_N_HTF = 3  (1H bars)
  SWING_N_LTF = 5  (15M bars)

Note: the last n bars of any DataFrame cannot have confirmed swings yet
(the right-side window is incomplete). This is intentional — no look-ahead.
"""

import numpy as np
import pandas as pd


def find_swing_highs(highs: np.ndarray, n: int = 5) -> np.ndarray:
    """
    Return a boolean array; True at index i if high[i] is a swing high.

    Uses strict fractal comparison (>): high[i] must be STRICTLY greater
    than all n bars on each side. Prevents false positives when multiple
    adjacent bars share the same high value.

    Parameters
    ----------
    highs : np.ndarray  — high prices
    n     : int         — bars on each side required (fractal window = 2n+1)
    """
    length = len(highs)
    result = np.zeros(length, dtype=bool)
    for i in range(n, length - n):
        if (all(highs[i] > highs[i - j] for j in range(1, n + 1)) and
                all(highs[i] > highs[i + j] for j in range(1, n + 1))):
            result[i] = True
    return result


def find_swing_lows(lows: np.ndarray, n: int = 5) -> np.ndarray:
    """
    Return a boolean array; True at index i if low[i] is a swing low.

    Uses strict fractal comparison (<): low[i] must be STRICTLY less than
    all n bars on each side.
    """
    length = len(lows)
    result = np.zeros(length, dtype=bool)
    for i in range(n, length - n):
        if (all(lows[i] < lows[i - j] for j in range(1, n + 1)) and
                all(lows[i] < lows[i + j] for j in range(1, n + 1))):
            result[i] = True
    return result


def get_swing_points(df: pd.DataFrame, n: int = 5):
    """
    Annotate a DataFrame with swing high / swing low columns.

    Adds:
        df['swing_high'] : bool — True where a swing high was confirmed
        df['swing_low']  : bool — True where a swing low was confirmed

    Returns the modified DataFrame (copy).
    """
    df = df.copy()
    highs = df["high"].to_numpy()
    lows  = df["low"].to_numpy()
    df["swing_high"] = find_swing_highs(highs, n)
    df["swing_low"]  = find_swing_lows(lows, n)
    return df


def get_confirmed_swing_highs(df: pd.DataFrame) -> pd.Series:
    """Return Series of swing high prices (NaN elsewhere). Requires swing_high column."""
    return df["high"].where(df["swing_high"])


def get_confirmed_swing_lows(df: pd.DataFrame) -> pd.Series:
    """Return Series of swing low prices (NaN elsewhere). Requires swing_low column."""
    return df["low"].where(df["swing_low"])
