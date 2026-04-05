"""
strategy/liquidity.py — Liquidity pool detection and sweep confirmation.

"Liquidity" refers to clusters of stop-loss orders sitting just beyond
swing highs (buy stops) or swing lows (sell stops).

Equal Highs / Equal Lows:
  Two swing highs (or lows) within LIQ_TOLERANCE % of each other form
  a liquidity pool. Stop orders accumulate above/below these levels.

Liquidity Sweep:
  A candle temporarily exceeds the equal-highs/lows level (taking out
  the stops), then closes back on the other side.

  Bullish sweep (of sell stops below equal lows):
    - Candle low goes BELOW the equal-lows level
    - Candle closes ABOVE the level (or closes below but next candle does)
    → Smart money has collected liquidity; bullish reversal expected

  Bearish sweep (of buy stops above equal highs):
    - Candle high goes ABOVE the equal-highs level
    - Candle closes BELOW the level
    → Bearish reversal expected

Sweep event fields:
  {
    'bar_idx'   : int,
    'timestamp' : pd.Timestamp,
    'direction' : 'bull'|'bear',   bull = swept sell-stops (bullish setup)
    'level'     : float,           the equal-highs/lows price level
  }
"""

from __future__ import annotations
import numpy as np
import pandas as pd
from config import LIQ_TOLERANCE


def find_equal_highs(df: pd.DataFrame, tolerance_pct: float = LIQ_TOLERANCE) -> list[dict]:
    """
    Find pairs of confirmed swing highs within `tolerance_pct` % of each other.

    Returns list of dicts: {bar_idx_a, bar_idx_b, level (average price)}
    Requires df to have 'swing_high' column (from get_swing_points).
    """
    sh_idx = df.index[df["swing_high"]].tolist()
    highs  = df["high"]
    pools  = []
    for i in range(len(sh_idx)):
        for j in range(i + 1, len(sh_idx)):
            hi_a = highs[sh_idx[i]]
            hi_b = highs[sh_idx[j]]
            pct_diff = abs(hi_a - hi_b) / max(hi_a, hi_b) * 100
            if pct_diff <= tolerance_pct:
                pools.append({
                    "bar_idx_a": df.index.get_loc(sh_idx[i]),
                    "bar_idx_b": df.index.get_loc(sh_idx[j]),
                    "level": (hi_a + hi_b) / 2,
                })
    return pools


def find_equal_lows(df: pd.DataFrame, tolerance_pct: float = LIQ_TOLERANCE) -> list[dict]:
    """
    Find pairs of confirmed swing lows within `tolerance_pct` % of each other.
    Requires df to have 'swing_low' column.
    """
    sl_idx = df.index[df["swing_low"]].tolist()
    lows   = df["low"]
    pools  = []
    for i in range(len(sl_idx)):
        for j in range(i + 1, len(sl_idx)):
            lo_a = lows[sl_idx[i]]
            lo_b = lows[sl_idx[j]]
            pct_diff = abs(lo_a - lo_b) / max(lo_a, lo_b) * 100
            if pct_diff <= tolerance_pct:
                pools.append({
                    "bar_idx_a": df.index.get_loc(sl_idx[i]),
                    "bar_idx_b": df.index.get_loc(sl_idx[j]),
                    "level": (lo_a + lo_b) / 2,
                })
    return pools


def detect_sweeps(df: pd.DataFrame, n_swing: int = 5, tolerance_pct: float = LIQ_TOLERANCE) -> list[dict]:
    """
    Detect all liquidity sweep events in a DataFrame.

    A sweep is confirmed when:
      - A candle's wick pierces through an equal-highs/lows level
      - The candle body (close) is back on the opposite side

    Returns chronologically sorted list of sweep event dicts.
    """
    from .swings import get_swing_points
    df = get_swing_points(df.copy(), n_swing)

    eq_highs = find_equal_highs(df, tolerance_pct)
    eq_lows  = find_equal_lows(df, tolerance_pct)

    highs  = df["high"].to_numpy()
    lows   = df["low"].to_numpy()
    closes = df["close"].to_numpy()
    idx    = df.index
    events = []

    # Bearish sweep: candle pierces ABOVE equal-highs, closes BELOW
    for pool in eq_highs:
        level     = pool["level"]
        start_bar = pool["bar_idx_b"]   # look for sweep after second swing high
        for i in range(start_bar + 1, len(df)):
            if highs[i] > level and closes[i] < level:
                events.append({
                    "bar_idx":   i,
                    "timestamp": idx[i],
                    "direction": "bear",   # bearish setup after sweeping buy-stops
                    "level":     level,
                })
                break  # one sweep per pool

    # Bullish sweep: candle pierces BELOW equal-lows, closes ABOVE
    for pool in eq_lows:
        level     = pool["level"]
        start_bar = pool["bar_idx_b"]
        for i in range(start_bar + 1, len(df)):
            if lows[i] < level and closes[i] > level:
                events.append({
                    "bar_idx":   i,
                    "timestamp": idx[i],
                    "direction": "bull",   # bullish setup after sweeping sell-stops
                    "level":     level,
                })
                break

    events.sort(key=lambda e: e["bar_idx"])
    return events


def liquidity_was_swept(sweeps: list[dict], direction: str, before_bar: int) -> bool:
    """
    Return True if at least one liquidity sweep of the given direction
    occurred before `before_bar`.

    Used to satisfy checklist item: "liquidity has already been cleared."
    """
    for sweep in sweeps:
        if sweep["bar_idx"] < before_bar and sweep["direction"] == direction:
            return True
    return False
