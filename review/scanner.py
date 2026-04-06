"""
review/scanner.py — Visual BOS+Sweep setup scanner for manual calibration.

Finds every BOS event that matches HTF bias AND has a prior liquidity sweep,
then opens an interactive candlestick chart in the browser for each one so
the user can mark which setups they would have taken (y/n).

Usage (via main.py):
    python main.py --symbol EURUSD --from 2024-01-01 --to 2024-06-01 --scan

Controls (in terminal after chart opens in browser):
    y  — Yes, I would take this trade
    n  — No, skip
    q  — Quit scanning
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import webbrowser
from datetime import datetime
from typing import Optional

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import config
from strategy.structure import detect_bos, get_htf_bias
from strategy.liquidity import detect_sweeps, liquidity_was_swept
from strategy.fvg       import detect_fvg, update_mitigation, fvg_near_price
from strategy.fibonacci import calculate_fib_levels

try:
    import plotly.graph_objects as go
    HAS_PLOTLY = True
except ImportError:
    HAS_PLOTLY = False


# ─── Setup candidate ─────────────────────────────────────────────────────────

class SetupCandidate:
    __slots__ = (
        "bar_idx", "bar_time", "direction",
        "bos", "sweeps", "fib", "fvgs",
        "has_fvg_near_entry", "all_conditions_met",
    )

    def __init__(self, bar_idx, bar_time, direction, bos, sweeps, fib, fvgs,
                 has_fvg_near_entry, all_conditions_met):
        self.bar_idx            = bar_idx
        self.bar_time           = bar_time
        self.direction          = direction
        self.bos                = bos
        self.sweeps             = sweeps
        self.fib                = fib
        self.fvgs               = fvgs
        self.has_fvg_near_entry = has_fvg_near_entry
        self.all_conditions_met = all_conditions_met


# ─── Scanner ─────────────────────────────────────────────────────────────────

def scan_setups(
    m15_df: pd.DataFrame,
    h1_df:  pd.DataFrame,
    symbol: str,
) -> list[SetupCandidate]:
    """
    Walk forward through M15 data and collect every BOS+Sweep candidate.
    Conditions 1-3 are required; 4-5 are flagged for display only.
    """
    min_bars = config.SWING_N_LTF * 2 + 10
    total    = len(m15_df) - min_bars

    candidates: list[SetupCandidate] = []
    seen_bos_bar_ids: set[int] = set()

    sig_recompute_at   = min_bars
    cached_last_bos    = None
    cached_sweeps      = []
    cached_fvg_list    = []
    cached_fvg_end     = 0
    prev_bos_bar_idx   = -1
    h1_bias_cache      = "none"
    h1_bias_recheck_at = 0

    print(f"  Scanning {len(m15_df):,} bars for setups…")

    for i in range(min_bars, len(m15_df)):
        bar      = m15_df.iloc[i]
        bar_time = m15_df.index[i]

        done = i - min_bars
        if done % 200 == 0:
            pct = done / max(total, 1) * 100
            print(f"\r  {pct:5.1f}%  candidates: {len(candidates)}   ",
                  end="", flush=True)

        # Refresh signals every SWING_N_LTF bars
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

        if cached_last_bos is None:
            continue

        # HTF bias check
        if i >= h1_bias_recheck_at:
            past_h1 = h1_df[h1_df.index < bar_time]
            if len(past_h1) >= config.SWING_N_HTF * 2 + 5:
                h1_bias_cache = get_htf_bias(past_h1, bar_time, n=config.SWING_N_HTF)
            h1_bias_recheck_at = i + 4

        if h1_bias_cache == "none":
            continue
        if cached_last_bos["direction"] != h1_bias_cache:
            continue

        # Liquidity swept
        if not liquidity_was_swept(cached_sweeps, h1_bias_cache,
                                   cached_last_bos["bar_idx"]):
            continue

        # Deduplicate per BOS bar
        bos_key = cached_last_bos["bar_idx"]
        if bos_key in seen_bos_bar_ids:
            continue
        seen_bos_bar_ids.add(bos_key)

        fib = calculate_fib_levels(
            direction    = cached_last_bos["direction"],
            impulse_low  = cached_last_bos["swing_low"],
            impulse_high = cached_last_bos["swing_high"],
        )

        for j in range(cached_fvg_end, i):
            c = m15_df.iloc[j]
            update_mitigation(cached_fvg_list, c["high"], c["low"])
        cached_fvg_end = i

        at_entry_zone = abs(bar["close"] - fib.entry) <= config.ENTRY_BUFFER * 3
        fvg_near      = fvg_near_price(cached_fvg_list, fib.entry,
                                        config.FVG_PROXIMITY, h1_bias_cache)

        candidates.append(SetupCandidate(
            bar_idx            = i,
            bar_time           = bar_time,
            direction          = h1_bias_cache,
            bos                = dict(cached_last_bos),
            sweeps             = list(cached_sweeps),
            fib                = fib,
            fvgs               = [dict(f) for f in cached_fvg_list],
            has_fvg_near_entry = fvg_near,
            all_conditions_met = at_entry_zone and fvg_near,
        ))

    print(f"\n  Scan complete — {len(candidates)} unique setups found")
    return candidates


# ─── Plotly HTML chart ───────────────────────────────────────────────────────

def _build_html(
    window: pd.DataFrame,
    candidate: SetupCandidate,
    index: int,
    total: int,
    bos_bar_loc: int,
    scan_bar_loc: int,
) -> str:
    """Build a self-contained HTML string with a Plotly candlestick chart."""
    fib = candidate.fib
    bos = candidate.bos
    direction = candidate.direction

    ts = window.index.astype(str).tolist()

    # ── Candlestick trace ────────────────────────────────────────────────────
    candle = go.Candlestick(
        x     = ts,
        open  = window["open"],
        high  = window["high"],
        low   = window["low"],
        close = window["close"],
        name  = "Price",
        increasing_line_color = "#26a69a",
        decreasing_line_color = "#ef5350",
    )

    shapes = []
    annotations = []

    # ── Horizontal level lines (as shapes) ───────────────────────────────────
    def hline(price, color, dash="dash"):
        return dict(
            type="line", xref="x", yref="y",
            x0=ts[0], x1=ts[-1],
            y0=price, y1=price,
            line=dict(color=color, width=1.5, dash=dash),
        )

    shapes += [
        hline(fib.tp,    "#00e676", dash="dash"),    # TP — green
        hline(fib.entry, "#ffd600", dash="dash"),    # Entry — gold
        hline(fib.sl,    "#f44336", dash="dash"),    # SL — red
        hline(bos["level"], "#29b6f6", dash="solid"),# BOS — blue
    ]

    # ── Labels on the right ──────────────────────────────────────────────────
    def label(price, text, color):
        return dict(
            x=ts[-1], y=price, xref="x", yref="y",
            text=f"<b>{text}</b>", showarrow=False,
            xanchor="left", font=dict(color=color, size=11),
        )

    annotations += [
        label(fib.tp,      f"TP  {fib.tp:.5f}",      "#00e676"),
        label(fib.entry,   f"Entry {fib.entry:.5f}",  "#ffd600"),
        label(fib.sl,      f"SL  {fib.sl:.5f}",       "#f44336"),
        label(bos["level"],f"BOS {bos['level']:.5f}", "#29b6f6"),
    ]

    # ── FVG zone rectangles ──────────────────────────────────────────────────
    for fvg in candidate.fvgs:
        if fvg.get("mitigated") or fvg.get("direction") != direction:
            continue
        fvg_start = str(fvg.get("timestamp", ts[0]))
        shapes.append(dict(
            type="rect", xref="x", yref="y",
            x0=fvg_start, x1=ts[-1],
            y0=fvg["bottom"], y1=fvg["top"],
            fillcolor="rgba(255,235,59,0.15)",
            line=dict(width=0),
        ))

    # ── BOS bar vertical line ─────────────────────────────────────────────────
    if 0 <= bos_bar_loc < len(ts):
        shapes.append(dict(
            type="line", xref="x", yref="paper",
            x0=ts[bos_bar_loc], x1=ts[bos_bar_loc],
            y0=0, y1=1,
            line=dict(color="#29b6f6", width=1, dash="dot"),
        ))
        annotations.append(dict(
            x=ts[bos_bar_loc], y=1, xref="x", yref="paper",
            text="BOS", showarrow=False, yanchor="top",
            font=dict(color="#29b6f6", size=10),
        ))

    # ── "Now" bar vertical line ───────────────────────────────────────────────
    if 0 <= scan_bar_loc < len(ts):
        shapes.append(dict(
            type="line", xref="x", yref="paper",
            x0=ts[scan_bar_loc], x1=ts[scan_bar_loc],
            y0=0, y1=1,
            line=dict(color="#00bcd4", width=1.5, dash="dot"),
        ))
        annotations.append(dict(
            x=ts[scan_bar_loc], y=1, xref="x", yref="paper",
            text="NOW", showarrow=False, yanchor="top",
            font=dict(color="#00bcd4", size=10),
        ))

    # ── Sweep markers ────────────────────────────────────────────────────────
    sweep_x, sweep_y, sweep_text = [], [], []
    for sw in candidate.sweeps:
        if sw.get("direction") == direction:
            sw_ts = str(sw.get("timestamp", ""))
            if sw_ts in ts:
                sw_idx = ts.index(sw_ts)
                sweep_x.append(sw_ts)
                sweep_y.append(window.iloc[sw_idx]["low"] * 0.9993)
                sweep_text.append("SWEEP")

    sweep_trace = go.Scatter(
        x=sweep_x, y=sweep_y,
        mode="markers+text",
        marker=dict(symbol="triangle-up", size=12, color="#e040fb"),
        text=sweep_text, textposition="bottom center",
        textfont=dict(color="#e040fb", size=9),
        name="Sweep",
        showlegend=False,
    )

    # ── Build figure ─────────────────────────────────────────────────────────
    cond_str = "✅ ALL CONDITIONS MET" if candidate.all_conditions_met else \
               ("🟡 FVG near entry" if candidate.has_fvg_near_entry else "⚪ Conditions 1–3 only")

    rr = (fib.tp_distance / fib.sl_distance) if fib.sl_distance > 0 else 0
    title = (f"Setup {index}/{total}  |  {direction.upper()}  |  "
             f"BOS @ {bos['level']:.5f}  |  R:R {rr:.1f}:1  |  {cond_str}")

    fig = go.Figure(data=[candle, sweep_trace])
    fig.update_layout(
        title=dict(text=title, font=dict(color="white", size=14)),
        paper_bgcolor="#131722",
        plot_bgcolor="#131722",
        font=dict(color="#d1d4dc"),
        xaxis=dict(
            rangeslider=dict(visible=False),
            gridcolor="#1e2130",
            showgrid=True,
            type="category",          # avoids weekend gaps
            tickangle=-45,
            nticks=20,
        ),
        yaxis=dict(gridcolor="#1e2130", showgrid=True),
        shapes=shapes,
        annotations=annotations,
        margin=dict(l=60, r=120, t=60, b=60),
        height=620,
        legend=dict(bgcolor="#1e2130"),
    )

    # Instruction banner at bottom
    fig.add_annotation(
        x=0.5, y=-0.12, xref="paper", yref="paper",
        text="<b>Go back to the Terminal and press  y = take  |  n = skip  |  q = quit</b>",
        showarrow=False, font=dict(color="#ffd600", size=13),
        bgcolor="#1e2130", borderpad=6,
    )

    return fig.to_html(full_html=True, include_plotlyjs="cdn", config={"scrollZoom": True})


def _show_chart(
    m15_df: pd.DataFrame,
    candidate: SetupCandidate,
    index: int,
    total: int,
    context_bars: int = 120,
) -> None:
    """Render chart to a temp HTML file and open in the default browser."""
    if not HAS_PLOTLY:
        print("  [no chart — install plotly: pip3 install plotly]")
        return

    bos_bar = candidate.bos["bar_idx"]
    i       = candidate.bar_idx
    start   = max(0, bos_bar - context_bars)
    end     = min(len(m15_df), i + 30)
    window  = m15_df.iloc[start:end].copy()

    if len(window) < 3:
        return

    html = _build_html(window, candidate, index, total,
                       bos_bar - start, i - start)

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".html", delete=False, prefix=f"setup_{index}_"
    ) as f:
        f.write(html)
        path = f.name

    webbrowser.open(f"file://{path}")


# ─── Interactive review loop ─────────────────────────────────────────────────

def run_scan(
    m15_df: pd.DataFrame,
    h1_df:  pd.DataFrame,
    symbol: str,
    output_path: Optional[str] = None,
) -> list[dict]:
    """
    Scan for setups, show interactive browser charts, collect y/n answers.
    Decisions are saved to a JSON file.
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

    if HAS_PLOTLY:
        print("  Each setup opens as an interactive chart in your browser.")
    else:
        print("  [!] plotly not installed — run: pip3 install plotly")
    print("  In the terminal:  y = take  |  n = skip  |  q = quit\n")

    decisions: list[dict] = []
    taken = 0

    for k, cand in enumerate(candidates, 1):
        fib = cand.fib
        bos = cand.bos
        rr  = fib.tp_distance / fib.sl_distance if fib.sl_distance > 0 else 0

        # Print summary
        flags = []
        if cand.has_fvg_near_entry:  flags.append("FVG✓")
        if cand.all_conditions_met:  flags.append("ENTRY-ZONE✓")
        flags_str = "  ".join(flags) if flags else "(cond 1-3 only)"

        print(f"  ── Setup {k}/{total} ─────────────────────────────────────────")
        print(f"     {cand.direction.upper()}  BOS @ {bos['level']:.5f}  "
              f"({bos['timestamp']})")
        print(f"     Entry={fib.entry:.5f}  SL={fib.sl:.5f}  "
              f"TP={fib.tp:.5f}  R:R={rr:.1f}:1")
        print(f"     {flags_str}")

        # Open chart in browser
        _show_chart(m15_df, cand, k, total)

        # Get answer
        while True:
            try:
                ans = input("  Take this trade? [y/n/q]: ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                ans = "q"
            if ans in ("y", "n", "q"):
                break
            print("  Please press y, n, or q.")

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
            "rr":                 round(rr, 2),
            "has_fvg_near_entry": cand.has_fvg_near_entry,
            "all_conditions_met": cand.all_conditions_met,
            "decision":           ans,
        }
        decisions.append(decision)

        if ans == "y":
            taken += 1
            print(f"  ✓ TAKEN  (total taken: {taken})")
        elif ans == "n":
            print(f"  ✗ Skipped")
        else:
            print(f"\n  Quitting scan early (reviewed {k}/{total} setups).")
            break

    with open(output_path, "w") as f:
        json.dump(decisions, f, indent=2)

    print(f"\n  ── Scan summary ─────────────────────────────────────────────")
    print(f"  Reviewed : {len(decisions)}")
    print(f"  Taken    : {taken}")
    print(f"  Saved to : {output_path}")

    if taken > 0 and decisions:
        taken_all     = sum(1 for d in decisions if d["decision"] == "y" and d["all_conditions_met"])
        taken_partial = sum(1 for d in decisions if d["decision"] == "y" and not d["all_conditions_met"])
        print(f"\n  Of your 'take' decisions:")
        print(f"    All 5 conditions met : {taken_all}")
        print(f"    Partial (cond 1-3)   : {taken_partial}")
    print()

    return decisions
