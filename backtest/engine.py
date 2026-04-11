"""
backtest/engine.py — Walk-forward backtest engine.

Two-phase architecture:
  Phase 1 (cold/expensive): pre-compute BOS / sweeps / FVGs / H1 bias once.
  Phase 2 (hot/cheap):      simulate trade execution bar by bar.

The Phase 1 results can be cached externally (see backtest/signal_cache.py)
and passed in via the `precomputed` arg, so changing risk parameters,
RR, hour filters, etc. only re-runs the cheap Phase 2.
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
from strategy.fvg       import (
    detect_fvg,
    update_mitigation,
    fvg_near_price,
    fvg_near_price_at,
    precompute_mitigation_indices,
)
from strategy.liquidity import detect_sweeps, liquidity_was_swept
from strategy.fibonacci import calculate_fib_levels, price_at_entry_zone
from backtest.trade     import Trade
from backtest.filters   import (
    passes_hours,
    passes_weekday,
    DailyTradeCounter,
    DEFAULT_WEEKDAYS,
)


def calculate_lot_size(risk_usd: float, sl_distance: float, symbol: str) -> float:
    pip_size  = config.PIP_SIZE.get(symbol, 0.0001)
    pip_value = config.PIP_VALUE_PER_LOT.get(symbol, 10.0)
    if sl_distance == 0 or pip_size == 0:
        return 0.0
    pips_at_risk = sl_distance / pip_size
    if pips_at_risk == 0:
        return 0.0
    return round(risk_usd / (pips_at_risk * pip_value), 2)


def precompute_signals(m15_df: pd.DataFrame, h1_df: pd.DataFrame,
                       swing_n_ltf: Optional[int] = None,
                       swing_n_htf: Optional[int] = None,
                       fvg_min_size: Optional[float] = None) -> dict:
    """
    Run all the expensive signal scans once. Returns a dict that can be
    passed back into run_backtest() via the `precomputed` kwarg, or saved
    via signal_cache.put() for re-use across runs.
    """
    swing_n_ltf  = swing_n_ltf  if swing_n_ltf  is not None else config.SWING_N_LTF
    swing_n_htf  = swing_n_htf  if swing_n_htf  is not None else config.SWING_N_HTF
    fvg_min_size = fvg_min_size if fvg_min_size is not None else config.FVG_MIN_SIZE

    print("  Pre-computing M15 signals… ", end="", flush=True)
    full_bos    = detect_bos(m15_df, n=swing_n_ltf)
    full_sweeps = detect_sweeps(m15_df, n_swing=swing_n_ltf)
    print(f"{len(full_bos)} BOS, {len(full_sweeps)} sweeps", flush=True)

    print("  Pre-computing H1 bias… ", end="", flush=True)
    h1_bos = detect_bos(h1_df, n=swing_n_htf)
    print(f"{len(h1_bos)} H1 BOS events", flush=True)

    print("  Pre-computing FVGs (vectorised mitigation)… ", end="", flush=True)
    fvgs = detect_fvg(m15_df, min_size=fvg_min_size)
    precompute_mitigation_indices(fvgs, m15_df)
    print(f"{len(fvgs)} FVGs", flush=True)

    return {
        "full_bos":    full_bos,
        "full_sweeps": full_sweeps,
        "h1_bos":      h1_bos,
        "fvgs":        fvgs,
        "swing_n_ltf": swing_n_ltf,
        "swing_n_htf": swing_n_htf,
    }


def run_backtest(
    m15_df: pd.DataFrame,
    h1_df:  pd.DataFrame,
    symbol: str,
    risk_per_trade: float = config.RISK_PER_TRADE,
    compound: bool = False,
    initial_capital: float = config.INITIAL_CAPITAL,
    risk_pct: float = 0.5,
    progress_callback=None,
    # ── New knobs ──────────────────────────────────────────────────────────
    rr: float = 3.0,
    require_fvg: Optional[bool] = None,
    min_fib_span: Optional[float] = None,
    entry_buffer: Optional[float] = None,
    hours_filter: Optional[tuple] = None,        # (start_h, end_h) Israel time
    weekday_filter: Optional[set] = None,        # set of {0..6}, Sun=0
    max_trades_per_day: int = 0,                 # 0 = unlimited
    cooldown_bars: Optional[int] = None,
    commission_per_lot: float = 0.0,             # USD round-trip per standard lot
    # ── Pre-computed signals (for warm path) ───────────────────────────────
    precomputed: Optional[dict] = None,
) -> list[Trade]:
    """
    Walk-forward bar-by-bar backtest.  Returns list of completed Trade objects.

    Risk modes:
      compound=False  → fixed `risk_per_trade` USD per trade
      compound=True   → risk = risk_pct% of current equity

    RR semantics:
      `rr` controls TP placement: TP = entry ± rr × sl_distance.
      Default 3.0 reproduces the original 1:3 fib geometry.

    Post-hoc filters (cheap, don't invalidate signal cache):
      hours_filter   = (start_hour, end_hour) in Israel time
      weekday_filter = set of weekdays to allow (Sun=0..Sat=6)
      max_trades_per_day = max entries per Israel calendar day
    """
    pip_size       = config.PIP_SIZE.get(symbol, 0.0001)
    pip_value      = config.PIP_VALUE_PER_LOT.get(symbol, 10.0)
    cumulative_pnl = 0.0  # tracked for compound mode

    # Resolve effective config (per-symbol or override)
    eff_min_span     = min_fib_span     if min_fib_span     is not None else config.get_min_fib_span(symbol)
    eff_entry_buffer = entry_buffer     if entry_buffer     is not None else config.get_entry_buffer(symbol)
    eff_require_fvg  = require_fvg      if require_fvg      is not None else config.REQUIRE_FVG
    eff_cooldown     = cooldown_bars    if cooldown_bars    is not None else config.ENTRY_COOLDOWN_BARS
    eff_weekdays     = weekday_filter   if weekday_filter   is not None else DEFAULT_WEEKDAYS

    all_trades: list[Trade] = []
    open_trade: Optional[Trade] = None
    _traded_bos: set = set()
    daily_counter = DailyTradeCounter(max_trades_per_day or 0)

    min_bars = (precomputed.get("swing_n_ltf", config.SWING_N_LTF)
                if precomputed else config.SWING_N_LTF) * 2 + 10
    total = len(m15_df) - min_bars
    t0    = time.time()

    # ── Phase 1: Signal pre-computation (or use cached) ──────────────────────
    if precomputed is not None:
        print("  Using pre-computed signals (warm path)", flush=True)
        full_bos    = precomputed["full_bos"]
        full_sweeps = precomputed["full_sweeps"]
        h1_bos      = precomputed["h1_bos"]
        fvgs        = precomputed["fvgs"]
    else:
        sigs = precompute_signals(m15_df, h1_df)
        full_bos    = sigs["full_bos"]
        full_sweeps = sigs["full_sweeps"]
        h1_bos      = sigs["h1_bos"]
        fvgs        = sigs["fvgs"]

    # Monotonic pointers
    bos_ptr = 0
    sw_ptr  = 0
    h1_ptr  = 0
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
            if progress_callback is not None:
                try:
                    progress_callback(pct / 100.0, len(all_trades), eta)
                except Exception:
                    pass

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
                if commission_per_lot > 0:
                    open_trade.pnl_usd -= commission_per_lot * open_trade.lot_size
                all_trades.append(open_trade)
                cumulative_pnl += open_trade.pnl_usd
                open_trade = None
            elif hit_sl:
                open_trade.close(open_trade.sl_price, bar_time, pip_value, pip_size)
                if commission_per_lot > 0:
                    open_trade.pnl_usd -= commission_per_lot * open_trade.lot_size
                all_trades.append(open_trade)
                cumulative_pnl += open_trade.pnl_usd
                open_trade = None

            if open_trade is not None:
                continue  # still in trade

        # ── Step 2: advance pointers ──────────────────────────────────────────
        while bos_ptr < len(full_bos) and full_bos[bos_ptr]["bar_idx"] <= i:
            bos_ptr += 1
        cached_last_bos = full_bos[bos_ptr - 1] if bos_ptr > 0 else None

        while sw_ptr < len(full_sweeps) and full_sweeps[sw_ptr]["bar_idx"] <= i:
            sw_ptr += 1
        cached_sweeps = full_sweeps[:sw_ptr]

        if cached_last_bos is None:
            continue

        # HTF bias — advance H1 BOS pointer
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

        # ── Fibonacci entry zone ──────────────────────────────────────────────
        fib = calculate_fib_levels(
            direction    = cached_last_bos["direction"],
            impulse_low  = cached_last_bos["swing_low"],
            impulse_high = cached_last_bos["swing_high"],
        )

        # Filter: minimum impulse leg size
        if fib.impulse_high - fib.impulse_low < eff_min_span:
            continue

        if not price_at_entry_zone(bar["close"], fib, eff_entry_buffer):
            continue

        # Duplicate filter: each BOS event can only generate one trade
        if cached_last_bos["bar_idx"] in _traded_bos:
            continue

        # ── Post-hoc filters: hours / weekday / max-per-day ───────────────────
        if hours_filter is not None:
            start_h, end_h = hours_filter
            if not passes_hours(bar_time, start_h, end_h):
                continue
        if not passes_weekday(bar_time, eff_weekdays):
            continue
        if not daily_counter.can_take(bar_time):
            continue

        # ── FVG check (vectorised, O(n_fvgs) per bar) ─────────────────────────
        if eff_require_fvg:
            if not fvg_near_price_at(fvgs, fib.entry, config.FVG_PROXIMITY,
                                      h1_bias_cache, i):
                continue

        # ── Compute entry / SL / TP with custom RR ────────────────────────────
        # Entry stays at the 75% fib. SL stays at the 100% fib. TP is recomputed
        # from the SL distance using the user-supplied risk-reward multiplier.
        entry_px = fib.entry
        sl_px    = fib.sl
        sl_dist  = abs(entry_px - sl_px)
        if sl_dist == 0:
            continue
        if cached_last_bos["direction"] == "bull":
            tp_px = entry_px + rr * sl_dist
        else:
            tp_px = entry_px - rr * sl_dist

        # ── Compute risk size ─────────────────────────────────────────────────
        if compound:
            current_equity = initial_capital + cumulative_pnl
            current_risk   = max(current_equity * risk_pct / 100.0, 1.0)
        else:
            current_risk = risk_per_trade
        lot = calculate_lot_size(current_risk, sl_dist, symbol)
        if lot <= 0:
            continue

        _traded_bos.add(cached_last_bos["bar_idx"])
        daily_counter.record(bar_time)

        # Resolve impulse swing timestamps for visual review
        sh_bar = cached_last_bos.get("swing_high_bar")
        sl_bar = cached_last_bos.get("swing_low_bar")
        sh_time = m15_df.index[sh_bar] if sh_bar is not None and sh_bar < len(m15_df) else None
        sl_time = m15_df.index[sl_bar] if sl_bar is not None and sl_bar < len(m15_df) else None

        open_trade = Trade(
            symbol      = symbol,
            direction   = h1_bias_cache,
            entry_price = entry_px,
            sl_price    = sl_px,
            tp_price    = tp_px,
            entry_time  = bar_time,
            lot_size    = lot,
            risk_usd    = current_risk,
            impulse_high      = cached_last_bos["swing_high"],
            impulse_low       = cached_last_bos["swing_low"],
            impulse_high_time = sh_time,
            impulse_low_time  = sl_time,
            result      = None,
        )
        open_trade._entry_bar = i

    print()  # newline after progress bar

    if open_trade is not None:
        open_trade.result = "open"
        all_trades.append(open_trade)

    elapsed = time.time() - t0
    print(f"  Done in {elapsed:.1f}s — {len(all_trades)} trades found")
    return all_trades
