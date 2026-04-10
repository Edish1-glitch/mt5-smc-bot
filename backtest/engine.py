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
from strategy.structure import detect_bos
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

    # ── Pre-compute ALL signals ONCE (O(n) total instead of O(n²)) ───────────
    print("  Pre-computing M15 signals… ", end="", flush=True)
    full_bos    = detect_bos(m15_df, n=config.SWING_N_LTF)
    full_sweeps = detect_sweeps(m15_df, n_swing=config.SWING_N_LTF)
    print(f"{len(full_bos)} BOS, {len(full_sweeps)} sweeps", flush=True)

    print("  Pre-computing H1 bias… ", end="", flush=True)
    h1_bos = detect_bos(h1_df, n=config.SWING_N_HTF)
    print(f"{len(h1_bos)} H1 BOS events", flush=True)

    # Monotonic pointers — advance as i increases (O(1) amortised per bar)
    bos_ptr  = 0   # full_bos[bos_ptr-1] is the last M15 BOS at or before bar i
    sw_ptr   = 0   # full_sweeps[:sw_ptr] are all sweeps at or before bar i
    h1_ptr   = 0   # h1_bos[h1_ptr-1] is the last H1 BOS before bar_time

    # FVG cache — rebuilt only when active BOS changes (≈20-30× total)
    cached_fvg_list  = []
    cached_fvg_end   = 0
    prev_bos_bar_idx = -1

    # H1 bias cache (updated via pointer, not recomputed)
    h1_bias_cache = "none"

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

        # ── Step 2: advance BOS + sweep pointers (O(1) amortised) ───────────
        while bos_ptr < len(full_bos) and full_bos[bos_ptr]["bar_idx"] <= i:
            bos_ptr += 1
        cached_last_bos = full_bos[bos_ptr - 1] if bos_ptr > 0 else None

        while sw_ptr < len(full_sweeps) and full_sweeps[sw_ptr]["bar_idx"] <= i:
            sw_ptr += 1
        cached_sweeps = full_sweeps[:sw_ptr]

        # ── Step 3: fast-exit checks ──────────────────────────────────────────
        if cached_last_bos is None:
            continue

        # FVG: rebuild only when active BOS changes (cheap — happens ~20-30×)
        new_bos_idx = cached_last_bos["bar_idx"]
        if new_bos_idx != prev_bos_bar_idx:
            cached_fvg_list  = detect_fvg(m15_df.iloc[:i], min_size=config.FVG_MIN_SIZE)
            cached_fvg_end   = 0
            prev_bos_bar_idx = new_bos_idx

        # HTF bias — advance H1 BOS pointer (O(1) amortised)
        while h1_ptr < len(h1_bos) and h1_bos[h1_ptr]["timestamp"] < bar_time:
            h1_ptr += 1
        h1_bias_cache = h1_bos[h1_ptr - 1]["direction"] if h1_ptr > 0 else "none"

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
        if config.REQUIRE_FVG:
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

        # Resolve impulse swing timestamps for visual review
        sh_bar = cached_last_bos.get("swing_high_bar")
        sl_bar = cached_last_bos.get("swing_low_bar")
        sh_time = m15_df.index[sh_bar] if sh_bar is not None and sh_bar < len(m15_df) else None
        sl_time = m15_df.index[sl_bar] if sl_bar is not None and sl_bar < len(m15_df) else None

        open_trade = Trade(
            symbol      = symbol,
            direction   = h1_bias_cache,
            entry_price = fib.entry,
            sl_price    = fib.sl,
            tp_price    = fib.tp,
            entry_time  = bar_time,
            lot_size    = lot,
            risk_usd    = risk_per_trade,
            impulse_high      = cached_last_bos["swing_high"],
            impulse_low       = cached_last_bos["swing_low"],
            impulse_high_time = sh_time,
            impulse_low_time  = sl_time,
            result      = None,
        )

    print()  # newline after progress bar

    if open_trade is not None:
        open_trade.result = "open"
        all_trades.append(open_trade)

    elapsed = time.time() - t0
    print(f"  Done in {elapsed:.1f}s — {len(all_trades)} trades found")
    return all_trades
