"""
main.py — Entry point for the SMC/ICT backtest.

Usage:
    # Mac/Linux (yfinance, אוטומטי):
    python main.py --symbol EURUSD --from 2024-01-01 --to 2024-06-01

    # Mac דרך MT5 bridge (Windows VPS):
    export MT5_BRIDGE_URL=http://<windows-ip>:5000
    python main.py --symbol EURUSD --from 2023-01-01 --to 2024-01-01

    # Windows עם MT5:
    python main.py --symbol EURUSD --from 2020-01-01 --to 2024-01-01

    # בחירת מקור ידנית:
    python main.py --symbol EURUSD --from 2024-01-01 --to 2024-06-01 --source yfinance
    python main.py --symbol EURUSD --from 2023-01-01 --to 2024-01-01 --source bridge
    python main.py --symbol EURUSD --from 2023-01-01 --to 2024-01-01 --source mt5

    # מ-CSV (Export מ-MT5):
    python main.py --symbol EURUSD --csv-m15 eurusd_m15.csv --csv-h1 eurusd_h1.csv \
                   --from 2022-01-01 --to 2024-01-01

    # ביקורת ויזואלית של עסקאות:
    python main.py --symbol EURUSD --from 2024-01-01 --to 2024-06-01 --review

    # סריקה ויזואלית ידנית (בחירת עסקאות):
    python main.py --symbol EURUSD --from 2024-01-01 --to 2024-06-01 --scan

Options:
    --symbol   : סמל/ים (e.g. EURUSD XAUUSD NAS100)
    --from     : תאריך התחלה YYYY-MM-DD
    --to       : תאריך סיום YYYY-MM-DD
    --source   : auto | mt5 | yfinance | bridge  (default: auto)
    --review   : הצגת גרפי נרות לכל עסקה
    --scan     : סריקה ויזואלית ידנית — בחר y/n לכל סטאפ
    --csv-m15  : נתיב CSV לנתוני 15M
    --csv-h1   : נתיב CSV לנתוני 1H
    --risk     : סיכון USD לעסקה (default: 500)
"""

import argparse
import os
import sys
import platform

import config
from data.fetcher import get_ohlcv, load_from_csv, _detect_source
from backtest.engine import run_backtest
from backtest.results import compute_stats, print_stats


def parse_args():
    p = argparse.ArgumentParser(description="SMC/ICT Strategy Backtester")
    p.add_argument("--serve", action="store_true",
                   help="Boot the FastAPI web server (mobile-first dashboard)")
    p.add_argument("--port", type=int, default=8000,
                   help="Port for --serve (default: 8000)")
    p.add_argument("--host", default="0.0.0.0",
                   help="Host for --serve (default: 0.0.0.0)")
    p.add_argument("--symbol", nargs="+",
                   help="MT5 symbol(s) to backtest (e.g. EURUSD XAUUSD)")
    p.add_argument("--from",   dest="date_from",
                   help="Start date YYYY-MM-DD")
    p.add_argument("--to",     dest="date_to",
                   help="End date YYYY-MM-DD")
    p.add_argument("--source", default="auto",
                   choices=["auto", "mt5", "oanda", "yfinance", "bridge", "dukascopy"],
                   help="Data source (default: auto-detect)")
    p.add_argument("--review", action="store_true",
                   help="Show candlestick chart review after backtest")
    p.add_argument("--scan", action="store_true",
                   help="Visual setup scanner — manually mark y/n for each BOS+Sweep setup")
    p.add_argument("--csv-m15", dest="csv_m15", default=None,
                   help="Path to CSV file for 15M OHLCV data")
    p.add_argument("--csv-h1",  dest="csv_h1",  default=None,
                   help="Path to CSV file for 1H OHLCV data")
    p.add_argument("--risk", type=float, default=config.RISK_PER_TRADE,
                   help=f"USD risk per trade (default: {config.RISK_PER_TRADE})")
    return p.parse_args()


def main():
    args = parse_args()

    # ── Server mode: boot FastAPI ────────────────────────────────────────────
    if args.serve:
        import uvicorn
        print(f"\n  🚀 Starting SMC Bot dashboard on http://{args.host}:{args.port}\n")
        uvicorn.run("web.api.server:app", host=args.host, port=args.port, log_level="info")
        return

    if not args.symbol or not args.date_from or not args.date_to:
        print("Error: --symbol, --from and --to are required (or use --serve)")
        sys.exit(1)

    all_stats = {}

    # Show active source
    active_source = args.source if args.source != "auto" else _detect_source()
    bridge_url = os.environ.get("MT5_BRIDGE_URL", "")
    print(f"\n  Platform: {platform.system()}  |  Data source: {active_source}", end="")
    if active_source == "bridge":
        print(f"  →  {bridge_url}", end="")
    print()

    for symbol in args.symbol:
        print(f"\nLoading data for {symbol}...")

        # Load 15M data
        if args.csv_m15:
            m15_df = load_from_csv(args.csv_m15, symbol, "M15")
            m15_df = m15_df[args.date_from: args.date_to]
        else:
            m15_df = get_ohlcv(symbol, "M15", args.date_from, args.date_to, source=args.source)

        # Load 1H data
        if args.csv_h1:
            h1_df = load_from_csv(args.csv_h1, symbol, "H1")
            h1_df = h1_df[args.date_from: args.date_to]
        else:
            h1_df = get_ohlcv(symbol, "H1", args.date_from, args.date_to, source=args.source)

        print(f"  15M bars: {len(m15_df):,}  |  1H bars: {len(h1_df):,}")

        # ── Scan mode: visual setup browser ──────────────────────────────────
        if args.scan:
            from review.scanner import run_scan
            run_scan(m15_df, h1_df, symbol)
            continue   # skip automated backtest when in scan mode

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
