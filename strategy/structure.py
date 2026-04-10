"""
strategy/structure.py — Market structure: BOS detection and HTF bias.

Break of Structure (BOS):
  Bullish BOS: a 15M candle closes ABOVE the previous confirmed swing high
               → market structure has shifted bullish
  Bearish BOS: a 15M candle closes BELOW the previous confirmed swing low
               → market structure has shifted bearish

HTF Bias (1H):
  Determined by the most recent confirmed BOS on the 1H chart.
  Bullish bias  → only long entries on 15M (hard filter, no counter-trend)
  Bearish bias  → only short entries on 15M

BOS event fields:
  {
    'bar_idx'  : int,         index in the DataFrame
    'timestamp': pd.Timestamp,
    'direction': 'bull'|'bear',
    'level'    : float,       the swing level that was broken
    'swing_low': float,       impulse swing low  (Fib 100% for longs)
    'swing_high': float,      impulse swing high (Fib 0%  for longs)
  }
"""

from __future__ import annotations
from typing import Literal
import pandas as pd
from .swings import get_swing_points


def detect_bos(df: pd.DataFrame, n: int = 5) -> list[dict]:
    """
    Scan a DataFrame for Break of Structure events.

    Parameters
    ----------
    df : DataFrame with columns open, high, low, close (DatetimeIndex)
    n  : swing detection window

    Returns
    -------
    List of BOS event dicts, chronologically ordered.
    """
    df = get_swing_points(df, n)
    closes = df["close"].to_numpy()
    highs  = df["high"].to_numpy()
    lows   = df["low"].to_numpy()
    swing_h = df["swing_high"].to_numpy()
    swing_l = df["swing_low"].to_numpy()
    idx     = df.index

    events = []
    last_sh_price = None   # most recent confirmed swing high price
    last_sh_bar   = None   # bar index of that swing high
    last_sl_price = None   # most recent confirmed swing low price
    last_sl_bar   = None

    # For fib anchoring: track the absolute HIGHEST high and LOWEST low
    # across every bar since the last BOS reset (not just fractal pivots).
    # This ensures the fib spans the full visible move, matching how a trader
    # would manually draw the fib tool across the entire impulse leg.
    max_high_price = None
    max_high_bar   = None
    min_low_price  = None
    min_low_bar    = None

    for i in range(len(df)):
        # Update the "last confirmed swing high/low" BEFORE checking breaks
        # (swing at i is confirmed only if i <= len-n-1, already handled by get_swing_points)
        if swing_h[i]:
            last_sh_price = highs[i]
            last_sh_bar   = i
        if swing_l[i]:
            last_sl_price = lows[i]
            last_sl_bar   = i

        # Track absolute high/low of every bar since reset (for fib anchoring)
        if max_high_price is None or highs[i] > max_high_price:
            max_high_price = highs[i]
            max_high_bar   = i
        if min_low_price is None or lows[i] < min_low_price:
            min_low_price = lows[i]
            min_low_bar   = i

        # Check bullish BOS: close above last swing high
        if last_sh_price is not None and closes[i] > last_sh_price:
            # Impulse leg for bullish BOS:
            #   High = the swing high that was broken
            #   Low  = the most recent confirmed swing low BEFORE the broken SH
            #          (this is the origin of the impulse leg — where Smart Money
            #           pushed price up from). If none, use the absolute low
            #           between the SH and BOS bar.
            impulse_high   = float(highs[last_sh_bar])
            swing_high_bar = last_sh_bar

            # Find the most recent swing low that occurred BEFORE the broken SH
            best_sl_price, best_sl_bar = None, None
            for j in range(last_sh_bar - 1, -1, -1):
                if swing_l[j]:
                    best_sl_price = lows[j]
                    best_sl_bar   = j
                    break

            if best_sl_bar is not None:
                # Use the actual lowest point between that swing low and the SH
                # (the impulse may have dipped lower between fractal pivots)
                seg           = lows[best_sl_bar:last_sh_bar + 1]
                impulse_low   = float(seg.min())
                swing_low_bar = best_sl_bar + int(seg.argmin())
            else:
                # Fallback: lowest low in the 50 bars before the SH
                seg_start     = max(0, last_sh_bar - 50)
                seg           = lows[seg_start:last_sh_bar + 1]
                impulse_low   = float(seg.min())
                swing_low_bar = seg_start + int(seg.argmin())

            events.append({
                "bar_idx":        i,
                "timestamp":      idx[i],
                "direction":      "bull",
                "level":          last_sh_price,
                "swing_low":      impulse_low,
                "swing_high":     impulse_high,
                "swing_high_bar": swing_high_bar,
                "swing_low_bar":  swing_low_bar,
            })
            last_sh_price  = None;  last_sh_bar   = None
            last_sl_price  = None;  last_sl_bar   = None
            max_high_price = None;  max_high_bar  = None
            min_low_price  = None;  min_low_bar   = None

        # Check bearish BOS: close below last swing low
        elif last_sl_price is not None and closes[i] < last_sl_price:
            # Impulse leg for bearish BOS:
            #   Low  = the swing low that was broken
            #   High = the most recent confirmed swing high BEFORE the broken SL
            #          (origin of the bearish impulse — where Smart Money sold from)
            impulse_low    = float(lows[last_sl_bar])
            swing_low_bar  = last_sl_bar

            # Find the most recent swing high that occurred BEFORE the broken SL
            best_sh_price, best_sh_bar = None, None
            for j in range(last_sl_bar - 1, -1, -1):
                if swing_h[j]:
                    best_sh_price = highs[j]
                    best_sh_bar   = j
                    break

            if best_sh_bar is not None:
                # Use the actual highest point between that swing high and the SL
                seg            = highs[best_sh_bar:last_sl_bar + 1]
                impulse_high   = float(seg.max())
                swing_high_bar = best_sh_bar + int(seg.argmax())
            else:
                # Fallback: highest high in the 50 bars before the SL
                seg_start      = max(0, last_sl_bar - 50)
                seg            = highs[seg_start:last_sl_bar + 1]
                impulse_high   = float(seg.max())
                swing_high_bar = seg_start + int(seg.argmax())

            events.append({
                "bar_idx":        i,
                "timestamp":      idx[i],
                "direction":      "bear",
                "level":          last_sl_price,
                "swing_low":      impulse_low,
                "swing_high":     impulse_high,
                "swing_high_bar": swing_high_bar,
                "swing_low_bar":  swing_low_bar,
            })
            last_sh_price  = None;  last_sh_bar   = None
            last_sl_price  = None;  last_sl_bar   = None
            max_high_price = None;  max_high_bar  = None
            min_low_price  = None;  min_low_bar   = None

    return events


def get_htf_bias(h1_df: pd.DataFrame, at_time: pd.Timestamp, n: int = 3) -> Literal["bull", "bear", "none"]:
    """
    Return the 1H market structure bias at `at_time`.

    Uses only fully-closed 1H candles before `at_time` (no look-ahead).

    Returns
    -------
    'bull'  — last BOS on 1H was bullish
    'bear'  — last BOS on 1H was bearish
    'none'  — no BOS detected yet (not enough data)
    """
    closed = h1_df[h1_df.index < at_time]
    if len(closed) < n * 2 + 5:
        return "none"

    events = detect_bos(closed, n)
    if not events:
        return "none"

    return events[-1]["direction"]
