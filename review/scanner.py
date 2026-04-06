"""
review/scanner.py — Visual BOS+Sweep setup scanner for manual calibration.

Finds every BOS event that matches HTF bias AND has a prior liquidity sweep,
then shows a candlestick chart for each one so the user can mark which setups
they would have taken (y/n).  Decisions are saved to a JSON file.

Usage (via main.py):
    python main.py --symbol EURUSD --from 2024-01-01 --to 2024-06-01 --scan

Controls:
    y  — Yes, I would take this trade
    n  — No, skip
    q  — Quit scanning
"""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import config
from strategy.structure  import detect_bos, get_htf_bias
from strategy.liquidity  import detect_sweeps, liquidity_was_swept
from strategy.fvg        import detect_fvg, update_mitigation, fvg_near_price
from strategy.fibonacci  import calculate_fib_levels

try:
    import matplotlib
    matplotlib.use("TkAgg")   # non-blocking backend; falls back gracefully
except Exception:
    pass

try:
    import matplotlib.pyplot as plt
    import matplotlib.patches as mpatches
    HAS_PLT = True
except ImportError:
    HAS_PLT = False

try:
    import mplfinance as mpf
    HAS_MPF = True
except ImportError:
    HAS_MPF = False


# ─── Data class for a candidate setup ────────────────────────────────────────

class SetupCandidate:
    """A BOS+Sweep candidate that passed conditions 1-3 (but not necessarily 4-5)."""
    __slots__ = (
        "bar_idx", "bar_time", "direction",
        "bos", "sweeps", "fib", "fvgs",
        "has_fvg_near_entry", "all_conditions_met",
    )

    def __init__(self, bar_idx, bar_time, direction, bos, sweeps, fib, fvgs,
                 has_fvg_near_entry, all_conditions_met):
        self.bar_idx              = bar_idx
        self.bar_time             = bar_time
        self.direction            = direction
        self.bos                  = bos
        self.sweeps               = sweeps
        self.fib                  = fib
        self.fvgs                 = fvgs
        self.has_fvg_near_entry   = has_fvg_near_entry
        self.all_conditions_met   = all_conditions_met


# ─── Scanner ─────────────────────────────────────────────────────────────────

def scan_setups(
    m15_df: pd.DataFrame,
    h1_df:  pd.DataFrame,
    symbol: str,
    dedupe_bars: int = 20,
) -> list[SetupCandidate]:
    """
    Walk forward through M15 data and collect every BOS+Sweep candidate.

    Conditions checked:
      1. M15 BOS exists matching HTF bias
      2. HTF (H1) bias matches BOS direction
      3. Liquidity was swept before the BOS
      4. (flagged) Price in 75% Fib entry zone
      5. (flagged) Active FVG near entry

    Returns list of SetupCandidate objects, one per unique BOS event found.
    Already-seen BOS events (same bar_idx) are deduplicated so we don't
    show the same setup 5 times.
    """
    min_bars = config.SWING_N_LTF * 2 + 10
    total    = len(m15_df) - min_bars
    t0       = time.time()

    candidates: list[SetupCandidate] = []
    seen_bos_bar_ids: set[int] = set()   # deduplicate on BOS bar_idx

    # Signal cache (same optimisation as the engine)
    sig_recompute_at  = min_bars
    cached_last_bos   = None
    cached_sweeps     = []
    cached_fvg_list   = []
    cached_fvg_end    = 0
    prev_bos_bar_idx  = -1
    h1_bias_cache     = "none"
    h1_bias_recheck_at = 0

    print(f"  Scanning {len(m15_df):,} bars for setups…")

    for i in range(min_bars, len(m15_df)):
        bar      = m15_df.iloc[i]
        bar_time = m15_df.index[i]

        done = i - min_bars
        if done % 200 == 0:
            pct = done / max(total, 1) * 100
            print(f"\r  {pct:5.1f}%  candidates found: {len(candidates)}   ",
                  end="", flush=True)

        # ── Refresh signals (every SWING_N_LTF bars) ─────────────────────────
        if i >= sig_recompute_at:
            past     = m15_df.iloc[:i]
            bos_list = detect_bos(past, n=config.SWING_N_LTF)
            sweeps   = detect_sweeps(past, n_swing=config.SWING_N_LTF)

            new_last_bos = bos_list[-1] if bos_list else None
            new_bos_idx  = new_last_bos["bar_idx"] if new_last_bos else -1

            if new_bos_idx != prev_bos_bar_idx:
                cached_fvg_list  = detect_fvg(past, min_size=config.FVG_MIN_SIZE)
                cached_fvg_end   = 0
                prev_bos_bar_idx = new_bos_idx

            cached_last_bos  = new_last_bos
            cached_sweeps    = sweeps
            sig_recompute_at = i + config.SWING_N_LTF

        # Condition 1: BOS exists
        if cached_last_bos is None:
            continue

        # Condition 2: HTF bias
        if i >= h1_bias_recheck_at:
            past_h1 = h1_df[h1_df.index < bar_time]
            if len(past_h1) >= config.SWING_N_HTF * 2 + 5:
                h1_bias_cache = get_htf_bias(past_h1, bar_time, n=config.SWING_N_HTF)
            h1_bias_recheck_at = i + 4

        if h1_bias_cache == "none":
            continue
        if cached_last_bos["direction"] != h1_bias_cache:
            continue

        # Condition 3: Liquidity swept
        if not liquidity_was_swept(cached_sweeps, h1_bias_cache,
                                   cached_last_bos["bar_idx"]):
            continue

        # Deduplicate: one candidate per BOS event
        bos_key = cached_last_bos["bar_idx"]
        if bos_key in seen_bos_bar_ids:
            continue
        seen_bos_bar_ids.add(bos_key)

        # Fibonacci levels
        fib = calculate_fib_levels(
            direction    = cached_last_bos["direction"],
            impulse_low  = cached_last_bos["swing_low"],
            impulse_high = cached_last_bos["swing_high"],
        )

        # FVG incremental mitigation up to this bar
        for j in range(cached_fvg_end, i):
            c = m15_df.iloc[j]
            update_mitigation(cached_fvg_list, c["high"], c["low"])
        cached_fvg_end = i

        # Condition 4+5 flags (for display, not filtering)
        at_entry_zone  = abs(bar["close"] - fib.entry) <= config.ENTRY_BUFFER * 3
        fvg_near       = fvg_near_price(cached_fvg_list, fib.entry,
                                         config.FVG_PROXIMITY, h1_bias_cache)
        all_met        = at_entry_zone and fvg_near

        candidates.append(SetupCandidate(
            bar_idx              = i,
            bar_time             = bar_time,
            direction            = h1_bias_cache,
            bos                  = dict(cached_last_bos),
            sweeps               = list(cached_sweeps),
            fib                  = fib,
            fvgs                 = [dict(f) for f in cached_fvg_list],
            has_fvg_near_entry   = fvg_near,
            all_conditions_met   = all_met,
        ))

    print(f"\n  Scan complete — {len(candidates)} unique setups found")
    return candidates


# ─── Chart rendering ─────────────────────────────────────────────────────────

def _plot_setup(
    m15_df: pd.DataFrame,
    candidate: SetupCandidate,
    index: int,
    total: int,
    context_bars: int = 100,
) -> None:
    """Render one setup candidate as an annotated candlestick chart."""
    if not HAS_PLT:
        print("  [WARNING] matplotlib not installed — cannot show charts")
        return

    bos  = candidate.bos
    fib  = candidate.fib
    i    = candidate.bar_idx

    # Window: show context_bars before the BOS, plus 30 bars after the scan bar
    bos_bar = bos["bar_idx"]
    start   = max(0, bos_bar - context_bars)
    end     = min(len(m15_df), i + 30)
    window  = m15_df.iloc[start:end].copy()

    if len(window) < 3:
        return

    plt.close("all")

    if HAS_MPF:
        _plot_mpf(window, candidate, index, total, bos_bar - start, i - start)
    else:
        _plot_plain(window, candidate, index, total, bos_bar - start, i - start)


def _plot_mpf(window, candidate, index, total, bos_offset, scan_offset):
    """mplfinance version."""
    bos = candidate.bos
    fib = candidate.fib

    addplots = []
    n = len(window)

    # ── Fib level horizontal lines ────────────────────────────────────────────
    for price, color, label in [
        (fib.entry, "gold",   "Entry 75%"),
        (fib.sl,    "red",    "SL 100%"),
        (fib.tp,    "lime",   "TP 0%"),
    ]:
        line = pd.Series(price, index=window.index)
        addplots.append(mpf.make_addplot(line, color=color, linestyle="--",
                                          width=1.2, alpha=0.85))

    # ── BOS level ─────────────────────────────────────────────────────────────
    bos_line = pd.Series(bos["level"], index=window.index)
    addplots.append(mpf.make_addplot(bos_line, color="deepskyblue",
                                      linestyle="-", width=1.0, alpha=0.7))

    # ── Scan-bar marker (where we are "now") ─────────────────────────────────
    scan_marker = pd.Series(np.nan, index=window.index)
    if 0 <= scan_offset < n:
        scan_marker.iloc[scan_offset] = window.iloc[scan_offset]["low"] * 0.9994
    addplots.append(mpf.make_addplot(scan_marker, type="scatter",
                                      markersize=100, marker="^", color="cyan"))

    # ── BOS bar marker ────────────────────────────────────────────────────────
    bos_marker = pd.Series(np.nan, index=window.index)
    if 0 <= bos_offset < n:
        bos_marker.iloc[bos_offset] = window.iloc[bos_offset]["high"] * 1.0006
    addplots.append(mpf.make_addplot(bos_marker, type="scatter",
                                      markersize=80, marker="v", color="deepskyblue"))

    cond_str = "ALL CONDITIONS MET" if candidate.all_conditions_met else \
               ("FVG near entry" if candidate.has_fvg_near_entry else "No FVG near entry")
    title = (f"[{index}/{total}] {candidate.direction.upper()}  "
             f"BOS@{bos['level']:.5f}  Entry={fib.entry:.5f}  "
             f"SL={fib.sl:.5f}  TP={fib.tp:.5f}  | {cond_str}")

    fig, axes = mpf.plot(
        window,
        type="candle",
        style="nightclouds",
        title=title,
        addplot=addplots,
        figsize=(15, 7),
        warn_too_much_data=99999,
        returnfig=True,
    )

    # Shade FVG zones
    ax = axes[0]
    for fvg in candidate.fvgs:
        if fvg.get("mitigated"):
            continue
        if fvg.get("direction") != candidate.direction:
            continue
        ax.axhspan(fvg["bottom"], fvg["top"],
                   alpha=0.15, color="yellow", zorder=0)

    plt.tight_layout()
    plt.pause(0.05)   # draw without blocking
    plt.show(block=False)


def _plot_plain(window, candidate, index, total, bos_offset, scan_offset):
    """Plain matplotlib fallback."""
    fig, ax = plt.subplots(figsize=(14, 6))
    colors = ["#26a69a" if r["close"] >= r["open"] else "#ef5350"
              for _, r in window.iterrows()]

    for k, (ts, row) in enumerate(window.iterrows()):
        c = colors[k]
        ax.plot([k, k], [row["low"], row["high"]], color=c, linewidth=0.8)
        ax.bar(k, abs(row["close"] - row["open"]),
               bottom=min(row["open"], row["close"]),
               color=c, width=0.7, alpha=0.9)

    fib = candidate.fib
    bos = candidate.bos

    for price, color, label in [
        (fib.entry, "gold",         "Entry 75%"),
        (fib.sl,    "red",          "SL 100%"),
        (fib.tp,    "lime",         "TP 0%"),
        (bos["level"], "deepskyblue", "BOS level"),
    ]:
        ax.axhline(price, color=color, linestyle="--", linewidth=1.2, label=label)

    # Shade FVG zones
    for fvg in candidate.fvgs:
        if fvg.get("mitigated") or fvg.get("direction") != candidate.direction:
            continue
        ax.axhspan(fvg["bottom"], fvg["top"], alpha=0.15, color="yellow", zorder=0)

    if 0 <= scan_offset < len(window):
        ax.axvline(scan_offset, color="cyan", linewidth=1.0, linestyle=":", alpha=0.7)
    if 0 <= bos_offset < len(window):
        ax.axvline(bos_offset, color="deepskyblue", linewidth=1.0, linestyle=":", alpha=0.7)

    cond_str = "ALL MET" if candidate.all_conditions_met else \
               ("FVG ok" if candidate.has_fvg_near_entry else "No FVG")
    ax.set_title(f"[{index}/{total}] {candidate.direction.upper()}  "
                 f"BOS@{bos['level']:.5f}  Entry={fib.entry:.5f}  "
                 f"SL={fib.sl:.5f}  TP={fib.tp:.5f}  | {cond_str}")
    ax.legend(fontsize=8)
    plt.tight_layout()
    plt.pause(0.05)
    plt.show(block=False)


# ─── Interactive review loop ─────────────────────────────────────────────────

def run_scan(
    m15_df: pd.DataFrame,
    h1_df:  pd.DataFrame,
    symbol: str,
    output_path: Optional[str] = None,
) -> list[dict]:
    """
    Scan for setups, show charts, collect y/n answers from the user.

    Returns list of decision dicts saved to output_path (JSON).
    """
    if output_path is None:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = f"scan_decisions_{symbol}_{ts}.json"

    candidates = scan_setups(m15_df, h1_df, symbol)

    if not candidates:
        print("\n  No BOS+Sweep setups found in this date range.")
        print("  Try a longer date range or check data quality.")
        return []

    total = len(candidates)
    print(f"\n  Found {total} candidate setups.")
    print("  For each chart:  y = take trade  |  n = skip  |  q = quit\n")

    if not HAS_PLT:
        print("  [WARNING] matplotlib not available — showing text summaries only.")

    decisions: list[dict] = []
    taken = 0

    for k, cand in enumerate(candidates, 1):
        fib = cand.fib
        bos = cand.bos

        # Text summary before chart
        cond_flags = []
        if cand.has_fvg_near_entry:
            cond_flags.append("FVG✓")
        if cand.all_conditions_met:
            cond_flags.append("ENTRY-ZONE✓")
        flags_str = "  ".join(cond_flags) if cond_flags else "(conditions 4-5 not fully met)"

        print(f"  ── Setup {k}/{total} ──────────────────────────────────────")
        print(f"     Direction : {cand.direction.upper()}")
        print(f"     BOS bar   : {bos['timestamp']}  level={bos['level']:.5f}")
        print(f"     Fib Entry : {fib.entry:.5f}  SL={fib.sl:.5f}  TP={fib.tp:.5f}")
        print(f"     R:R       : {fib.tp_distance/fib.sl_distance:.1f}:1" if fib.sl_distance > 0 else "     R:R       : n/a")
        print(f"     Conditions: {flags_str}")

        if HAS_PLT:
            _plot_setup(m15_df, cand, k, total)

        # Get user input
        while True:
            try:
                ans = input("  Take this trade? [y/n/q]: ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                ans = "q"

            if ans in ("y", "n", "q"):
                break
            print("  Please press y, n, or q.")

        if HAS_PLT:
            plt.close("all")

        decision = {
            "index":              k,
            "symbol":             symbol,
            "direction":          cand.direction,
            "bar_time":           str(cand.bar_time),
            "bos_level":          bos["level"],
            "bos_timestamp":      str(bos["timestamp"]),
            "fib_entry":          fib.entry,
            "fib_sl":             fib.sl,
            "fib_tp":             fib.tp,
            "rr":                 round(fib.tp_distance / fib.sl_distance, 2) if fib.sl_distance > 0 else 0,
            "has_fvg_near_entry": cand.has_fvg_near_entry,
            "all_conditions_met": cand.all_conditions_met,
            "decision":           ans,
        }
        decisions.append(decision)

        if ans == "y":
            taken += 1
            print(f"  ✓ Marked as TAKEN  (total taken: {taken})")
        elif ans == "n":
            print(f"  ✗ Skipped")
        else:  # q
            print(f"\n  Quitting scan early (reviewed {k}/{total} setups).")
            break

    # Save decisions
    with open(output_path, "w") as f:
        json.dump(decisions, f, indent=2)

    print(f"\n  ── Scan summary ──────────────────────────────────────────")
    print(f"  Reviewed : {len(decisions)}")
    print(f"  Taken    : {taken}")
    print(f"  Saved to : {output_path}")
    print()

    # Show which conditions correlated with "take" decisions
    if decisions:
        taken_all    = sum(1 for d in decisions if d["decision"] == "y" and d["all_conditions_met"])
        taken_partial = sum(1 for d in decisions if d["decision"] == "y" and not d["all_conditions_met"])
        if taken > 0:
            print(f"  Of your 'take' decisions:")
            print(f"    All 5 conditions met : {taken_all}")
            print(f"    Partial (cond 1-3)   : {taken_partial}")
            print()

    return decisions
