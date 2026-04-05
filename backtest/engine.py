"""
backtest/engine.py — Walk-forward backtest engine.

Iterates through historical 15M bars one at a time (no look-ahead).
At each bar:
  1. Check if any open trade's SL or TP was hit → close it
  2. If no open trade, check all entry conditions:
       a. 1H bias matches trade direction (hard filter)
       b. Bullish/bearish BOS detected on 15M
       c. Liquidity was swept before the BOS
       d. Price has retraced to the 75% Fibonacci level
       e. Unmitigated FVG is near the 75% level
  3. If all conditions met → open trade with fixed $RISK_PER_TRADE

"Set and forget": once a trade is open, no modification is made.
The trade closes only when SL or TP is hit.
"""

from __future__ import annotations
import pandas as pd
import numpy as np
from typing import Optional

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import config
from strategy.swings import get_swing_points
from strategy.structure import detect_bos, get_htf_bias
from strategy.fvg import detect_fvg, update_mitigation, fvg_near_price
from strategy.liquidity import detect_sweeps, liquidity_was_swept
from strategy.fibonacci import calculate_fib_levels, price_at_entry_zone
from backtest.trade import Trade


def calculate_lot_size(risk_usd: float, sl_distance: float, symbol: str) -> float:
    """
    Calculate lot size so that hitting the SL loses exactly `risk_usd`.

    lot_size = risk_usd / (sl_distance / pip_size * pip_value_per_lot)
    """
    pip_size  = config.PIP_SIZE.get(symbol, 0.0001)
    pip_value = config.PIP_VALUE_PER_LOT.get(symbol, 10.0)
    if sl_distance == 0:
        return 0.0
    pips_at_risk = sl_distance / pip_size
    if pips_at_risk == 0:
        return 0.0
    return round(risk_usd / (pips_at_risk * pip_value), 2)


def run_backtest(
    m15_df: pd.DataFrame,
    h1_df:  pd.DataFrame,
    symbol: str,
    risk_per_trade: float = config.RISK_PER_TRADE,
) -> list[Trade]:
    """
    Run the full backtest on pre-loaded DataFrames.

    Parameters
    ----------
    m15_df         : 15M OHLCV DataFrame (DatetimeIndex, UTC)
    h1_df          : 1H  OHLCV DataFrame (DatetimeIndex, UTC)
    symbol         : e.g. "EURUSD"
    risk_per_trade : fixed USD risk per trade (default from config)

    Returns
    -------
    List of completed Trade objects.
    """
    pip_size  = config.PIP_SIZE.get(symbol, 0.0001)
    pip_value = config.PIP_VALUE_PER_LOT.get(symbol, 10.0)

    # Pre-compute 15M structure signals on the full dataset (for BOS/FVG/sweeps)
    # The engine will use only past data at each bar via slicing
    all_trades: list[Trade] = []
    open_trade: Optional[Trade] = None

    # We need at least SWING_N*2 + a few bars of context
    min_bars = config.SWING_N_LTF * 2 + 10

    for i in range(min_bars, len(m15_df)):
        bar       = m15_df.iloc[i]
        bar_time  = m15_df.index[i]
        bar_high  = bar["high"]
        bar_low   = bar["low"]
        bar_close = bar["close"]

        # ── Step 1: manage open trade (set-and-forget: just check SL/TP) ──
        if open_trade is not None:
            hit_sl = hit_tp = False
            if open_trade.direction == "bull":
                hit_sl = bar_low  <= open_trade.sl_price
                hit_tp = bar_high >= open_trade.tp_price
            else:
                hit_sl = bar_high >= open_trade.sl_price
                hit_tp = bar_low  <= open_trade.tp_price

            if hit_tp:
                open_trade.close(open_trade.tp_price, bar_time, pip_value, pip_size)
                all_trades.append(open_trade)
                open_trade = None
            elif hit_sl:
                open_trade.close(open_trade.sl_price, bar_time, pip_value, pip_size)
                all_trades.append(open_trade)
                open_trade = None
            # Both hit in same bar → TP wins (conservative; could also use SL)
            # If both triggered, we already closed with TP above, so SL check is skipped

            if open_trade is not None:
                continue  # still in trade, skip entry logic

        # ── Step 2: check entry conditions using only past data ──

        # Slice: use bars up to (not including) current bar for signal detection
        past_m15 = m15_df.iloc[: i]
        past_h1  = h1_df[h1_df.index < bar_time]

        if len(past_h1) < config.SWING_N_HTF * 2 + 5:
            continue

        # Condition 1: 1H bias (hard filter)
        htf_bias = get_htf_bias(past_h1, bar_time, n=config.SWING_N_HTF)
        if htf_bias == "none":
            continue

        # Conditions 2–3: BOS + liquidity sweep on 15M
        bos_events = detect_bos(past_m15, n=config.SWING_N_LTF)
        if not bos_events:
            continue

        last_bos = bos_events[-1]

        # BOS direction must match HTF bias
        if last_bos["direction"] != htf_bias:
            continue

        sweeps = detect_sweeps(past_m15, n_swing=config.SWING_N_LTF)
        if not liquidity_was_swept(sweeps, htf_bias, last_bos["bar_idx"]):
            continue

        # Condition 4: calculate 75% Fibonacci entry zone
        fib = calculate_fib_levels(
            direction    = last_bos["direction"],
            impulse_low  = last_bos["swing_low"],
            impulse_high = last_bos["swing_high"],
        )

        if not price_at_entry_zone(bar_close, fib, config.ENTRY_BUFFER):
            continue

        # Condition 5: unmitigated FVG near the 75% level
        fvg_list = detect_fvg(past_m15)
        # Update mitigation up to current bar
        for j in range(len(past_m15)):
            c = past_m15.iloc[j]
            update_mitigation(fvg_list, c["high"], c["low"])

        if not fvg_near_price(fvg_list, fib.entry, config.FVG_PROXIMITY, htf_bias):
            continue

        # ── All conditions met → open trade ──
        lot = calculate_lot_size(risk_per_trade, fib.sl_distance, symbol)
        if lot <= 0:
            continue

        open_trade = Trade(
            symbol      = symbol,
            direction   = htf_bias,
            entry_price = fib.entry,
            sl_price    = fib.sl,
            tp_price    = fib.tp,
            entry_time  = bar_time,
            lot_size    = lot,
            risk_usd    = risk_per_trade,
            result      = None,
        )

    # Close any trade still open at end of data (mark as open/incomplete)
    if open_trade is not None:
        open_trade.result = "open"
        all_trades.append(open_trade)

    return all_trades
