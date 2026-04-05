"""
main.py — Entry point for the SMC/ICT backtest.

Usage:
    # Run backtest on EURUSD from 2020 to 2024:
    python main.py --symbol EURUSD --from 2020-01-01 --to 2024-01-01

    # Run on multiple symbols:
    python main.py --symbol EURUSD XAUUSD NAS100 --from 2022-01-01 --to 2024-01-01

    # Run and show visual trade review charts:
    python main.py --symbol EURUSD --from 2024-01-01 --to 2024-06-01 --review

    # Load data from CSV instead of MT5 (for Linux/Mac):
    python main.py --symbol EURUSD --csv-m15 eurusd_m15.csv --csv-h1 eurusd_h1.csv \
                   --from 2022-01-01 --to 2024-01-01

Options:
    --symbol   : one or more MT5 symbol names
    --from     : start date (YYYY-MM-DD)
    --to       : end date (YYYY-MM-DD)
    --review   : show candlestick charts of detected trades
    --csv-m15  : path to CSV file for 15M data (skips MT5 download)
    --csv-h1   : path to CSV file for 1H data
    --risk     : USD risk per trade (default: 500)
"""

import argparse
import sys

import config
from data.fetcher import get_ohlcv, load_from_csv
from backtest.engine import run_backtest
from backtest.results import compute_stats, print_stats


def parse_args():
    p = argparse.ArgumentParser(description="SMC/ICT Strategy Backtester")
    p.add_argument("--symbol", nargs="+", required=True,
                   help="MT5 symbol(s) to backtest (e.g. EURUSD XAUUSD)")
    p.add_argument("--from",   dest="date_from", required=True,
                   help="Start date YYYY-MM-DD")
    p.add_argument("--to",     dest="date_to",   required=True,
                   help="End date YYYY-MM-DD")
    p.add_argument("--review", action="store_true",
                   help="Show candlestick chart review after backtest")
    p.add_argument("--csv-m15", dest="csv_m15", default=None,
                   help="Path to CSV file for 15M OHLCV data")
    p.add_argument("--csv-h1",  dest="csv_h1",  default=None,
                   help="Path to CSV file for 1H OHLCV data")
    p.add_argument("--risk", type=float, default=config.RISK_PER_TRADE,
                   help=f"USD risk per trade (default: {config.RISK_PER_TRADE})")
    return p.parse_args()


def main():
    args = parse_args()
    all_stats = {}

    for symbol in args.symbol:
        print(f"\nLoading data for {symbol}...")

        # Load 15M data
        if args.csv_m15:
            m15_df = load_from_csv(args.csv_m15, symbol, "M15")
            m15_df = m15_df[args.date_from: args.date_to]
        else:
            m15_df = get_ohlcv(symbol, "M15", args.date_from, args.date_to)

        # Load 1H data
        if args.csv_h1:
            h1_df = load_from_csv(args.csv_h1, symbol, "H1")
            h1_df = h1_df[args.date_from: args.date_to]
        else:
            h1_df = get_ohlcv(symbol, "H1", args.date_from, args.date_to)

        print(f"  15M bars: {len(m15_df):,}  |  1H bars: {len(h1_df):,}")

        # Run backtest
        print(f"  Running backtest...")
        trades = run_backtest(m15_df, h1_df, symbol, risk_per_trade=args.risk)
        print(f"  Trades found: {len(trades)}")

        # Compute and display stats
        stats = compute_stats(trades, config.INITIAL_CAPITAL)
        print_stats(stats, symbol)
        all_stats[symbol] = stats

        # Optional visual review
        if args.review and trades:
            from review.chart import review_all_trades
            review_all_trades(m15_df, trades, max_charts=20)

    # Combined summary if multiple symbols
    if len(args.symbol) > 1:
        print("\n" + "═" * 50)
        print("  COMBINED SUMMARY")
        print("═" * 50)
        for sym, s in all_stats.items():
            if s.get("total_trades", 0) > 0:
                print(f"  {sym:10s}  {s['total_trades']:4d} trades  "
                      f"WR {s['win_rate_pct']:5.1f}%  "
                      f"PF {s['profit_factor']:5.2f}  "
                      f"Net ${s['net_pnl_usd']:+.0f}")


if __name__ == "__main__":
    main()
