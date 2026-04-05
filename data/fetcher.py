"""
data/fetcher.py — Historical OHLCV data download and caching.

On Windows with MT5 installed: uses the MetaTrader5 Python library.
On Linux/Mac (or offline): loads from CSV or Parquet files in data/cache/.

Usage:
    from data.fetcher import get_ohlcv
    df = get_ohlcv("EURUSD", "H1", "2020-01-01", "2024-01-01")
"""

import os
import pandas as pd
from pathlib import Path

CACHE_DIR = Path(__file__).parent / "cache"
CACHE_DIR.mkdir(exist_ok=True)

# MT5 timeframe string → integer constant mapping (for mt5 library)
_MT5_TF = {
    "M1":  1,
    "M5":  5,
    "M15": 15,
    "M30": 30,
    "H1":  16385,
    "H4":  16388,
    "D1":  16408,
}


def get_ohlcv(symbol: str, timeframe: str, date_from: str, date_to: str) -> pd.DataFrame:
    """
    Return OHLCV DataFrame for the given symbol and timeframe.

    Columns: open, high, low, close, volume
    Index:   DatetimeIndex (UTC)

    Tries cache first; falls back to MT5 download on Windows.
    """
    cache_path = CACHE_DIR / f"{symbol}_{timeframe}_{date_from}_{date_to}.parquet"

    if cache_path.exists():
        df = pd.read_parquet(cache_path)
        return df

    # Try MT5 download
    try:
        df = _fetch_from_mt5(symbol, timeframe, date_from, date_to)
        df.to_parquet(cache_path)
        return df
    except ImportError:
        raise RuntimeError(
            "MetaTrader5 library not available (Linux/Mac). "
            "Run on Windows with MT5 installed, or place a CSV file at:\n"
            f"  {CACHE_DIR / symbol}_{timeframe}.csv\n"
            "with columns: time,open,high,low,close,volume"
        )


def load_from_csv(csv_path: str, symbol: str, timeframe: str) -> pd.DataFrame:
    """
    Load OHLCV data from a CSV file exported from MT5.
    Expected columns: time, open, high, low, close, tick_volume (or volume)
    """
    df = pd.read_csv(csv_path, parse_dates=["time"])
    df = df.rename(columns={"tick_volume": "volume"})
    df = df.set_index("time").sort_index()
    df = df[["open", "high", "low", "close", "volume"]]
    return df


def _fetch_from_mt5(symbol: str, timeframe: str, date_from: str, date_to: str) -> pd.DataFrame:
    """Download historical bars from a running MT5 terminal (Windows only)."""
    import MetaTrader5 as mt5
    from datetime import datetime, timezone

    if not mt5.initialize():
        raise RuntimeError(f"MT5 initialize() failed: {mt5.last_error()}")

    tf_const = _MT5_TF.get(timeframe)
    if tf_const is None:
        raise ValueError(f"Unknown timeframe: {timeframe}")

    dt_from = datetime.fromisoformat(date_from).replace(tzinfo=timezone.utc)
    dt_to   = datetime.fromisoformat(date_to).replace(tzinfo=timezone.utc)

    rates = mt5.copy_rates_range(symbol, tf_const, dt_from, dt_to)
    mt5.shutdown()

    if rates is None or len(rates) == 0:
        raise RuntimeError(f"No data returned for {symbol} {timeframe}")

    df = pd.DataFrame(rates)
    df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
    df = df.set_index("time").rename(columns={"tick_volume": "volume"})
    df = df[["open", "high", "low", "close", "volume"]]
    return df
