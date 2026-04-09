"""
download_data.py — Download free historical OHLCV data from Dukascopy.

No API key. No account. No cost. Bank-quality forex data going back 10+ years.

Usage:
    python3 download_data.py --symbol EURUSD --from 2023-01-01 --to 2024-04-01

Output (saved to data/cache/):
    EURUSD_M15_dukascopy.csv
    EURUSD_H1_dukascopy.csv

Then run the scanner:
    python3 scan_server.py --symbol EURUSD --from 2023-01-01 --to 2024-04-01 --source dukascopy

Supported symbols:
    Forex : EURUSD GBPUSD USDJPY USDCHF AUDUSD USDCAD NZDUSD EURGBP EURJPY GBPJPY
    Metals: XAUUSD XAGUSD
    Notes : NAS100/US500 may have limited history on Dukascopy
"""

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

from data.fetcher import _fetch_from_dukascopy

CACHE_DIR = ROOT / "data" / "cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)


def main():
    p = argparse.ArgumentParser(description="Download Dukascopy historical OHLCV data")
    p.add_argument("--symbol", required=True, help="e.g. EURUSD")
    p.add_argument("--from",   dest="date_from", required=True, help="YYYY-MM-DD")
    p.add_argument("--to",     dest="date_to",   required=True, help="YYYY-MM-DD")
    args = p.parse_args()

    symbol = args.symbol.upper()
    print(f"\n  Dukascopy data download: {symbol}  {args.date_from} → {args.date_to}")
    print(f"  (no API key required, free forever)\n")

    for tf in ("M15", "H1"):
        out = CACHE_DIR / f"{symbol}_{tf}_dukascopy.csv"

        if out.exists():
            print(f"  [{tf}] Already cached → {out.name}  (delete to re-download)")
            continue

        print(f"  [{tf}] Downloading 1-min candles and resampling to {tf}…")
        try:
            df = _fetch_from_dukascopy(symbol, tf, args.date_from, args.date_to)
        except Exception as e:
            print(f"\n  ERROR: {e}")
            sys.exit(1)

        df.index.name = "time"
        df.to_csv(out)
        print(f"  [{tf}] Saved {len(df):,} bars → {out.name}")

    print(f"\n  Done! Now run:")
    print(f"  python3 scan_server.py --symbol {symbol} "
          f"--from {args.date_from} --to {args.date_to} --source dukascopy\n")


if __name__ == "__main__":
    main()
