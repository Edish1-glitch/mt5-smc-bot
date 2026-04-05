"""
backtest/results.py — Performance statistics and equity curve.

Computes standard trading performance metrics from a list of Trade objects.
"""

from __future__ import annotations
import pandas as pd
import numpy as np
from backtest.trade import Trade


def compute_stats(trades: list[Trade], initial_capital: float) -> dict:
    """
    Compute performance statistics for a list of completed trades.

    Returns a dict with:
      total_trades, wins, losses, win_rate, avg_win_usd, avg_loss_usd,
      expectancy_usd, net_pnl_usd, max_drawdown_usd, max_drawdown_pct,
      profit_factor, avg_rr, sharpe_ratio (simplified daily)
    """
    closed = [t for t in trades if t.result in ("win", "loss")]
    if not closed:
        return {"total_trades": 0}

    wins   = [t for t in closed if t.result == "win"]
    losses = [t for t in closed if t.result == "loss"]

    win_rate    = len(wins) / len(closed) * 100
    avg_win     = np.mean([t.pnl_usd for t in wins])  if wins   else 0.0
    avg_loss    = np.mean([t.pnl_usd for t in losses]) if losses else 0.0
    expectancy  = (win_rate / 100) * avg_win + (1 - win_rate / 100) * avg_loss
    net_pnl     = sum(t.pnl_usd for t in closed)

    gross_profit = sum(t.pnl_usd for t in wins)   if wins   else 0.0
    gross_loss   = abs(sum(t.pnl_usd for t in losses)) if losses else 1.0
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf")

    avg_rr = np.mean([t.risk_reward for t in closed])

    # Equity curve and drawdown
    equity = [initial_capital]
    for t in closed:
        equity.append(equity[-1] + t.pnl_usd)
    equity_arr   = np.array(equity)
    peak         = np.maximum.accumulate(equity_arr)
    drawdown_arr = equity_arr - peak
    max_dd_usd   = float(drawdown_arr.min())
    max_dd_pct   = float((drawdown_arr / peak).min() * 100)

    return {
        "total_trades":    len(closed),
        "wins":            len(wins),
        "losses":          len(losses),
        "open_trades":     len([t for t in trades if t.result == "open"]),
        "win_rate_pct":    round(win_rate, 2),
        "avg_win_usd":     round(avg_win, 2),
        "avg_loss_usd":    round(avg_loss, 2),
        "expectancy_usd":  round(expectancy, 2),
        "net_pnl_usd":     round(net_pnl, 2),
        "gross_profit":    round(gross_profit, 2),
        "gross_loss":      round(gross_loss, 2),
        "profit_factor":   round(profit_factor, 3),
        "avg_rr":          round(avg_rr, 2),
        "max_dd_usd":      round(max_dd_usd, 2),
        "max_dd_pct":      round(max_dd_pct, 2),
        "final_equity":    round(equity[-1], 2),
    }


def print_stats(stats: dict, symbol: str = "") -> None:
    label = f" [{symbol}]" if symbol else ""
    print(f"\n{'═'*50}")
    print(f"  BACKTEST RESULTS{label}")
    print(f"{'═'*50}")
    if stats.get("total_trades", 0) == 0:
        print("  No completed trades found.")
        return
    print(f"  Total trades    : {stats['total_trades']}")
    print(f"  Wins / Losses   : {stats['wins']} / {stats['losses']}")
    print(f"  Win rate        : {stats['win_rate_pct']}%")
    print(f"  Avg win         : ${stats['avg_win_usd']}")
    print(f"  Avg loss        : ${stats['avg_loss_usd']}")
    print(f"  Expectancy      : ${stats['expectancy_usd']} per trade")
    print(f"  Net P&L         : ${stats['net_pnl_usd']}")
    print(f"  Profit factor   : {stats['profit_factor']}")
    print(f"  Avg R:R         : {stats['avg_rr']}")
    print(f"  Max drawdown    : ${stats['max_dd_usd']} ({stats['max_dd_pct']}%)")
    print(f"  Final equity    : ${stats['final_equity']}")
    print(f"{'═'*50}\n")


def equity_curve(trades: list[Trade], initial_capital: float) -> pd.Series:
    """Return a pandas Series of equity values after each closed trade."""
    closed = [t for t in trades if t.result in ("win", "loss")]
    closed.sort(key=lambda t: t.exit_time)
    values = [initial_capital]
    times  = [closed[0].entry_time if closed else pd.Timestamp.now()]
    for t in closed:
        values.append(values[-1] + t.pnl_usd)
        times.append(t.exit_time)
    return pd.Series(values, index=times, name="equity")
