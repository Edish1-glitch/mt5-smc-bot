"""
review/chart.py — Visual trade review with annotated candlestick charts.

Usage:
    python main.py --symbol EURUSD --from 2024-01-01 --to 2024-03-01 --review

Renders each detected trade as a candlestick chart (15M) showing:
  • The BOS that triggered the setup
  • The liquidity sweep that preceded it
  • The FVG zone
  • The Fibonacci entry / SL / TP levels
  • Entry and exit markers (green/red)

Requires: matplotlib, mplfinance
"""

from __future__ import annotations
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches

try:
    import mplfinance as mpf
    HAS_MPF = True
except ImportError:
    HAS_MPF = False

from backtest.trade import Trade


def plot_trade(
    m15_df: pd.DataFrame,
    trade: Trade,
    context_bars: int = 80,
    fib_levels: dict | None = None,
    fvg_zones: list[dict] | None = None,
    title: str = "",
) -> None:
    """
    Plot a single trade on a candlestick chart.

    Parameters
    ----------
    m15_df       : full 15M DataFrame
    trade        : the Trade object to visualize
    context_bars : how many bars before entry to show
    fib_levels   : dict with keys 'entry', 'sl', 'tp'
    fvg_zones    : list of FVG dicts with 'top', 'bottom', 'direction'
    title        : chart title
    """
    # Window: context_bars before entry to a few bars after exit
    entry_loc = m15_df.index.searchsorted(trade.entry_time)
    if trade.exit_time is not None:
        exit_loc = m15_df.index.searchsorted(trade.exit_time) + 5
    else:
        exit_loc = min(entry_loc + 100, len(m15_df))

    start = max(0, entry_loc - context_bars)
    window = m15_df.iloc[start:exit_loc].copy()

    if not HAS_MPF:
        _plot_simple(window, trade, fib_levels, fvg_zones, title)
        return

    # Build addplots for Fib levels and FVG zones
    addplots = []

    if fib_levels:
        for label, price, color in [
            ("Entry (75%)", fib_levels.get("entry"), "gold"),
            ("SL (100%)",   fib_levels.get("sl"),    "red"),
            ("TP (0%)",     fib_levels.get("tp"),     "lime"),
        ]:
            if price is not None:
                line = pd.Series(price, index=window.index)
                addplots.append(mpf.make_addplot(line, color=color, linestyle="--", width=1.2))

    # Entry / exit markers
    entry_marker = pd.Series(np.nan, index=window.index)
    if trade.entry_time in window.index:
        entry_marker[trade.entry_time] = window.loc[trade.entry_time, "low"] * 0.9995

    exit_marker = pd.Series(np.nan, index=window.index)
    if trade.exit_time is not None and trade.exit_time in window.index:
        exit_marker[trade.exit_time] = window.loc[trade.exit_time, "high"] * 1.0005

    if entry_marker.notna().any():
        addplots.append(mpf.make_addplot(entry_marker, type="scatter", markersize=80,
                                          marker="^", color="cyan"))
    if exit_marker.notna().any():
        color = "lime" if trade.result == "win" else "red"
        addplots.append(mpf.make_addplot(exit_marker, type="scatter", markersize=80,
                                          marker="v", color=color))

    result_str = trade.result.upper() if trade.result else "OPEN"
    pnl_str    = f"${trade.pnl_usd:+.2f}" if trade.result in ("win", "loss") else ""
    full_title = title or f"{trade.symbol} {trade.direction.upper()} | {result_str} {pnl_str}"

    mpf.plot(
        window,
        type="candle",
        style="nightclouds",
        title=full_title,
        addplot=addplots if addplots else None,
        figsize=(14, 7),
        warn_too_much_data=99999,
    )
    plt.show()


def _plot_simple(window: pd.DataFrame, trade: Trade, fib_levels, fvg_zones, title) -> None:
    """Fallback chart using plain matplotlib (no mplfinance)."""
    fig, ax = plt.subplots(figsize=(14, 6))
    for i, (ts, row) in enumerate(window.iterrows()):
        color = "green" if row["close"] >= row["open"] else "red"
        ax.plot([i, i], [row["low"], row["high"]], color=color, linewidth=0.8)
        ax.bar(i, abs(row["close"] - row["open"]),
               bottom=min(row["open"], row["close"]),
               color=color, width=0.6, alpha=0.8)

    if fib_levels:
        ax.axhline(fib_levels.get("entry"), color="gold",  linestyle="--", label="Entry 75%")
        ax.axhline(fib_levels.get("sl"),    color="red",   linestyle="--", label="SL 100%")
        ax.axhline(fib_levels.get("tp"),    color="lime",  linestyle="--", label="TP 0%")

    ax.set_title(title or f"{trade.symbol} {trade.direction.upper()} | {trade.result}")
    ax.legend()
    plt.tight_layout()
    plt.show()


def review_all_trades(
    m15_df: pd.DataFrame,
    trades: list[Trade],
    max_charts: int = 20,
) -> None:
    """
    Display up to `max_charts` trades for manual review.
    Press Ctrl+C or close the window to skip to the next.
    """
    subset = trades[:max_charts]
    print(f"\nShowing {len(subset)} of {len(trades)} trades for review.")
    for i, trade in enumerate(subset):
        print(f"  [{i+1}/{len(subset)}] {trade.direction.upper()} | "
              f"{trade.entry_time} → {trade.exit_time} | "
              f"{trade.result} ${trade.pnl_usd:+.2f}")
        try:
            plot_trade(m15_df, trade, title=f"Trade {i+1}/{len(subset)}")
        except KeyboardInterrupt:
            print("  Skipped.")
            continue
