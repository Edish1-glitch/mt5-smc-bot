"""
backtest/engine.py — Walk-forward backtest engine (optimised).

Key optimisation: BOS / sweeps / FVGs are NOT recomputed from scratch on
every bar.  Instead we use a lightweight incremental approach:
  • Signals (BOS, sweeps) are re-scanned once every SWING_N_LTF bars
    (swing points only form every n bars, so scanning more often is wasted work).
  • FVG mitigation is updated one bar at a time (incremental, not full re-scan).
  • get_htf_bias() result is cached across bars where the H1 window hasn't grown.

Complexity drops from O(n³) → O(n · n/k) ≈ O(n²/k) where k = SWING_N_LTF=5.
For 5 760 M15 bars the engine now runs in a few seconds instead of minutes.
"""

from __future__ import annotations
import sys, os, time
import pandas as pd
import numpy as np
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import config
from strategy.swings    import get_swing_points
from strategy.structure import detect_bos, get_htf_bias
from strategy.fvg       import detect_fvg, update_mitigation, fvg_near_price
from strategy.liquidity import detect_sweeps, liquidity_was_swept
from strategy.fibonacci import calculate_fib_levels, price_at_entry_zone
from backtest.trade     import Trade


def calculate_lot_size(risk_usd: float, sl_distance: float, symbol: str) -> float:
    pip_size  = config.PIP_SIZE.get(symbol, 0.0001)
    pip_value = config.PIP_VALUE_PER_LOT.get(symbol, 10.0)
    if sl_distance == 0 or pip_size == 0:
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
    Walk-forward bar-by-bar backtest.  Returns list of completed Trade objects.
    """
    pip_size  = config.PIP_SIZE.get(symbol, 0.0001)
    pip_value = config.PIP_VALUE_PER_LOT.get(symbol, 10.0)

    all_trades: list[Trade] = []
    open_trade: Optional[Trade] = None

    min_bars = config.SWING_N_LTF * 2 + 10
    total    = len(m15_df) - min_bars
    t0       = time.time()

    # ── Signal cache ──────────────────────────────────────────────────────────
    # Recomputed every SWING_N_LTF bars (new swings only form every n bars)
    sig_recompute_at  = min_bars
    cached_last_bos   = None   # last BOS event dict (or None)
    cached_sweeps     = []
    cached_fvg_list   = []
    cached_fvg_end    = 0      # index up to which mitigation has been applied
    prev_bos_bar_idx  = -1     # detect when BOS changes → reset FVG cache

    # H1 bias cache (only changes when a new H1 candle closes above/below a swing)
    h1_bias_cache     = "none"
    h1_bias_recheck_at = 0     # bar index when we should re-check HTF bias

    for i in range(min_bars, len(m15_df)):
        bar      = m15_df.iloc[i]
        bar_time = m15_df.index[i]

        # ── Progress indicator ────────────────────────────────────────────────
        done = i - min_bars
        if done % 200 == 0:
            pct     = done / max(total, 1) * 100
            elapsed = time.time() - t0
            eta     = (elapsed / max(done, 1)) * (total - done)
            print(f"\r  {pct:5.1f}%  bar {i}/{len(m15_df)}  "
                  f"trades={len(all_trades)}  "
                  f"ETA {eta:.0f}s   ", end="", flush=True)

        # ── Step 1: manage open trade ─────────────────────────────────────────
        if open_trade is not None:
            if open_trade.direction == "bull":
                hit_sl = bar["low"]  <= open_trade.sl_price
                hit_tp = bar["high"] >= open_trade.tp_price
            else:
                hit_sl = bar["high"] >= open_trade.sl_price
                hit_tp = bar["low"]  <= open_trade.tp_price

            if hit_tp:
                open_trade.close(open_trade.tp_price, bar_time, pip_value, pip_size)
                all_trades.append(open_trade)
                open_trade = None
            elif hit_sl:
                open_trade.close(open_trade.sl_price, bar_time, pip_value, pip_size)
                all_trades.append(open_trade)
                open_trade = None

            if open_trade is not None:
                continue  # still in trade

        # ── Step 2: refresh M15 signals (every SWING_N_LTF bars) ─────────────
        if i >= sig_recompute_at:
            past = m15_df.iloc[:i]
            bos_list = detect_bos(past, n=config.SWING_N_LTF)
            sweeps   = detect_sweeps(past, n_swing=config.SWING_N_LTF)

            new_last_bos = bos_list[-1] if bos_list else None

            # If the most recent BOS changed, rebuild FVG list from scratch
            new_bos_idx = new_last_bos["bar_idx"] if new_last_bos else -1
            if new_bos_idx != prev_bos_bar_idx:
                cached_fvg_list  = detect_fvg(past, min_size=config.FVG_MIN_SIZE)
                cached_fvg_end   = 0
                prev_bos_bar_idx = new_bos_idx

            cached_last_bos  = new_last_bos
            cached_sweeps    = sweeps
            sig_recompute_at = i + config.SWING_N_LTF

        # ── Step 3: fast-exit checks (cheap) ─────────────────────────────────
        if cached_last_bos is None:
            continue

        # HTF bias — re-check every H1 bar (≈ every 4 M15 bars)
        if i >= h1_bias_recheck_at:
            past_h1 = h1_df[h1_df.index < bar_time]
            if len(past_h1) >= config.SWING_N_HTF * 2 + 5:
                h1_bias_cache = get_htf_bias(past_h1, bar_time, n=config.SWING_N_HTF)
            h1_bias_recheck_at = i + 4   # re-check every ~4 bars (≈ 1 H1 candle)

        if h1_bias_cache == "none":
            continue
        if cached_last_bos["direction"] != h1_bias_cache:
            continue
        if not liquidity_was_swept(cached_sweeps, h1_bias_cache,
                                   cached_last_bos["bar_idx"]):
            continue

        # Fibonacci entry zone
        fib = calculate_fib_levels(
            direction    = cached_last_bos["direction"],
            impulse_low  = cached_last_bos["swing_low"],
            impulse_high = cached_last_bos["swing_high"],
        )
        if not price_at_entry_zone(bar["close"], fib, config.ENTRY_BUFFER):
            continue

        # ── Step 4: FVG — incremental mitigation ─────────────────────────────
        # Only iterate bars we haven't checked yet
        for j in range(cached_fvg_end, i):
            c = m15_df.iloc[j]
            update_mitigation(cached_fvg_list, c["high"], c["low"])
        cached_fvg_end = i

        if not fvg_near_price(cached_fvg_list, fib.entry,
                              config.FVG_PROXIMITY, h1_bias_cache):
            continue

        # ── All conditions met → open trade ──────────────────────────────────
        lot = calculate_lot_size(risk_per_trade, fib.sl_distance, symbol)
        if lot <= 0:
            continue

        open_trade = Trade(
            symbol      = symbol,
            direction   = h1_bias_cache,
            entry_price = fib.entry,
            sl_price    = fib.sl,
            tp_price    = fib.tp,
            entry_time  = bar_time,
            lot_size    = lot,
            risk_usd    = risk_per_trade,
            result      = None,
        )

    print()  # newline after progress bar

    if open_trade is not None:
        open_trade.result = "open"
        all_trades.append(open_trade)

    elapsed = time.time() - t0
    print(f"  Done in {elapsed:.1f}s — {len(all_trades)} trades found")
    return all_trades
