"""
strategy/fvg.py — Fair Value Gap (Imbalance) detection.

A Fair Value Gap is a 3-candle pattern where the middle candle's move
is so strong that it leaves a price gap between candles 1 and 3:

  Bullish FVG: candle[i-1].high < candle[i+1].low
               (gap above candle i-1 and below candle i+1)

  Bearish FVG: candle[i-1].low > candle[i+1].high
               (gap below candle i-1 and above candle i+1)

An FVG is "mitigated" once price trades back into the gap range.
Only unmitigated FVGs are valid entry zones.

FVG dict fields:
  {
    'bar_idx'   : int,          the middle candle's index
    'timestamp' : pd.Timestamp,
    'direction' : 'bull'|'bear',
    'top'       : float,        upper boundary of the gap
    'bottom'    : float,        lower boundary of the gap
    'mitigated' : bool,
  }
"""

from __future__ import annotations
import pandas as pd
import numpy as np
from config import FVG_MIN_SIZE


def detect_fvg(df: pd.DataFrame, min_size: float = FVG_MIN_SIZE) -> list[dict]:
    """
    Scan DataFrame for all Fair Value Gaps.

    Note: FVG at bar i requires bars i-1 and i+1, so the last bar
    cannot produce an FVG yet (no look-ahead).

    Returns list of FVG dicts (mitigated=False initially).
    """
    highs  = df["high"].to_numpy()
    lows   = df["low"].to_numpy()
    idx    = df.index
    fvgs   = []

    for i in range(1, len(df) - 1):
        # Bullish FVG: gap between candle[i-1] high and candle[i+1] low
        if lows[i + 1] > highs[i - 1]:
            gap_size = lows[i + 1] - highs[i - 1]
            if gap_size >= min_size:
                fvgs.append({
                    "bar_idx":   i,
                    "timestamp": idx[i],
                    "direction": "bull",
                    "top":       lows[i + 1],
                    "bottom":    highs[i - 1],
                    "mitigated": False,
                })

        # Bearish FVG: gap between candle[i-1] low and candle[i+1] high
        elif highs[i + 1] < lows[i - 1]:
            gap_size = lows[i - 1] - highs[i + 1]
            if gap_size >= min_size:
                fvgs.append({
                    "bar_idx":   i,
                    "timestamp": idx[i],
                    "direction": "bear",
                    "top":       lows[i - 1],
                    "bottom":    highs[i + 1],
                    "mitigated": False,
                })

    return fvgs


def update_mitigation(fvgs: list[dict], candle_high: float, candle_low: float) -> None:
    """
    Mark FVGs as mitigated if the current candle trades into them.
    Modifies the list in place.
    """
    for fvg in fvgs:
        if fvg["mitigated"]:
            continue
        if fvg["direction"] == "bull" and candle_low <= fvg["top"]:
            fvg["mitigated"] = True
        elif fvg["direction"] == "bear" and candle_high >= fvg["bottom"]:
            fvg["mitigated"] = True


def fvg_near_price(fvgs: list[dict], price: float, proximity: float, direction: str) -> bool:
    """
    Return True if there is an unmitigated FVG of the given direction
    whose zone overlaps or is within `proximity` of `price`.

    Used to confirm the 75% Fibonacci level is near an imbalance.
    """
    for fvg in fvgs:
        if fvg["mitigated"]:
            continue
        if fvg["direction"] != direction:
            continue
        # Check if price is within proximity of the FVG zone
        zone_mid = (fvg["top"] + fvg["bottom"]) / 2
        if abs(price - zone_mid) <= proximity:
            return True
        # Or if price falls inside the zone
        if fvg["bottom"] - proximity <= price <= fvg["top"] + proximity:
            return True
    return False


def get_active_fvgs(fvgs: list[dict], direction: str) -> list[dict]:
    """Return all unmitigated FVGs of the given direction."""
    return [f for f in fvgs if not f["mitigated"] and f["direction"] == direction]


def precompute_mitigation_indices(fvgs: list[dict], df: pd.DataFrame) -> None:
    """
    Vectorised pre-computation of the bar index at which each FVG gets mitigated.

    Adds a "mit_idx" key to each fvg (int or None if never mitigated within the
    DataFrame). Also flips "mitigated" to True for any FVG that has a mit_idx
    set, so existing per-bar checks short-circuit immediately.

    Replaces the per-bar Python loop in update_mitigation() — runs in O(n_fvgs)
    NumPy operations instead of O(n_bars * n_fvgs) Python operations.
    """
    if not fvgs:
        return
    highs = df["high"].to_numpy()
    lows  = df["low"].to_numpy()
    n_bars = len(df)

    for fvg in fvgs:
        start = fvg["bar_idx"] + 2  # FVG only valid AFTER candle i+1
        if start >= n_bars:
            fvg["mit_idx"] = None
            continue
        if fvg["direction"] == "bull":
            # Mitigated when low <= top
            mask = lows[start:] <= fvg["top"]
        else:
            # Mitigated when high >= bottom
            mask = highs[start:] >= fvg["bottom"]
        if mask.any():
            fvg["mit_idx"] = start + int(mask.argmax())
        else:
            fvg["mit_idx"] = None


def fvg_is_active_at(fvg: dict, bar_idx: int) -> bool:
    """O(1) check whether an FVG is unmitigated at the given bar index.
    Requires precompute_mitigation_indices() to have been called first."""
    mit = fvg.get("mit_idx")
    if mit is None:
        return bar_idx >= fvg["bar_idx"] + 2  # not mitigated, just needs to exist
    return fvg["bar_idx"] + 2 <= bar_idx < mit


def fvg_near_price_at(fvgs: list[dict], price: float, proximity: float,
                       direction: str, bar_idx: int) -> bool:
    """
    Vectorised version of fvg_near_price that uses pre-computed mitigation
    indices instead of the per-bar mitigated flag. ~10x faster.
    """
    for fvg in fvgs:
        if fvg["direction"] != direction:
            continue
        if not fvg_is_active_at(fvg, bar_idx):
            continue
        zone_mid = (fvg["top"] + fvg["bottom"]) / 2
        if abs(price - zone_mid) <= proximity:
            return True
        if fvg["bottom"] - proximity <= price <= fvg["top"] + proximity:
            return True
    return False
