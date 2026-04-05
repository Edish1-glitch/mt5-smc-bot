"""
data/fetcher.py — Historical OHLCV data download and caching.

Sources (selected automatically or via --source flag):
  'mt5'      — MetaTrader5 Python lib (Windows only, MT5 must be running)
  'yfinance' — Yahoo Finance via yfinance (Mac/Linux, free, limited history)
  'bridge'   — MT5 REST bridge server (any OS → Windows VPS running mt5_bridge/server.py)
               Set env var MT5_BRIDGE_URL=http://<host>:5000

Auto-detection order: bridge (if MT5_BRIDGE_URL set) → mt5 (Windows) → yfinance

Usage:
    from data.fetcher import get_ohlcv
    df = get_ohlcv("EURUSD", "H1", "2020-01-01", "2024-01-01")
    df = get_ohlcv("EURUSD", "H1", "2020-01-01", "2024-01-01", source="yfinance")
"""

import os
import sys
import platform
import pandas as pd
from pathlib import Path

CACHE_DIR = Path(__file__).parent / "cache"
CACHE_DIR.mkdir(exist_ok=True)

# ── MT5 timeframe string → integer constant ──────────────────────────────────
_MT5_TF = {
    "M1":  1,
    "M5":  5,
    "M15": 15,
    "M30": 30,
    "H1":  16385,
    "H4":  16388,
    "D1":  16408,
}

# ── yfinance symbol mapping (MT5 name → Yahoo ticker) ────────────────────────
_YF_SYMBOL = {
    "EURUSD":  "EURUSD=X",
    "GBPUSD":  "GBPUSD=X",
    "USDJPY":  "USDJPY=X",
    "USDCHF":  "USDCHF=X",
    "AUDUSD":  "AUDUSD=X",
    "USDCAD":  "USDCAD=X",
    "NZDUSD":  "NZDUSD=X",
    "XAUUSD":  "GC=F",        # Gold futures
    "XAGUSD":  "SI=F",        # Silver futures
    "NAS100":  "NQ=F",        # Nasdaq-100 futures
    "US500":   "ES=F",        # S&P 500 futures
    "US30":    "YM=F",        # Dow Jones futures
    "BTCUSD":  "BTC-USD",
    "ETHUSD":  "ETH-USD",
}

# ── yfinance interval mapping (MT5 TF → yfinance interval) ───────────────────
# Limitations: 1m/2m/5m/15m/30m → last 60 days only
#              60m/90m           → last 730 days only
#              1d+               → unlimited
_YF_INTERVAL = {
    "M1":  "1m",
    "M5":  "5m",
    "M15": "15m",
    "M30": "30m",
    "H1":  "1h",
    "H4":  "4h",
    "D1":  "1d",
}

# ── History limits for intraday yfinance data ────────────────────────────────
_YF_MAX_DAYS = {
    "M1": 7, "M5": 60, "M15": 60, "M30": 60,
    "H1": 730, "H4": 730,
    "D1": 9999,
}


def _detect_source() -> str:
    """Auto-detect the best available data source."""
    if os.environ.get("MT5_BRIDGE_URL"):
        return "bridge"
    if platform.system() == "Windows":
        return "mt5"
    return "yfinance"


def get_ohlcv(
    symbol: str,
    timeframe: str,
    date_from: str,
    date_to: str,
    source: str = "auto",
) -> pd.DataFrame:
    """
    Return OHLCV DataFrame for the given symbol and timeframe.

    Columns: open, high, low, close, volume
    Index:   DatetimeIndex (UTC)

    Parameters
    ----------
    symbol    : MT5 symbol name (e.g. 'EURUSD', 'XAUUSD')
    timeframe : 'M15', 'H1', 'D1', etc.
    date_from : 'YYYY-MM-DD'
    date_to   : 'YYYY-MM-DD'
    source    : 'auto' | 'mt5' | 'yfinance' | 'bridge'
    """
    if source == "auto":
        source = _detect_source()

    cache_key = f"{symbol}_{timeframe}_{date_from}_{date_to}_{source}"
    cache_path = CACHE_DIR / f"{cache_key}.parquet"

    if cache_path.exists():
        return pd.read_parquet(cache_path)

    if source == "mt5":
        df = _fetch_from_mt5(symbol, timeframe, date_from, date_to)
    elif source == "yfinance":
        df = _fetch_from_yfinance(symbol, timeframe, date_from, date_to)
    elif source == "bridge":
        df = _fetch_from_bridge(symbol, timeframe, date_from, date_to)
    else:
        raise ValueError(f"Unknown source: {source!r}. Use 'mt5', 'yfinance', or 'bridge'.")

    df.to_parquet(cache_path)
    return df


def load_from_csv(csv_path: str, symbol: str = "", timeframe: str = "") -> pd.DataFrame:
    """
    Load OHLCV data from a CSV file exported from MT5.
    Expected columns: time, open, high, low, close, tick_volume (or volume)
    """
    df = pd.read_csv(csv_path, parse_dates=["time"])
    df = df.rename(columns={"tick_volume": "volume"})
    df = df.set_index("time").sort_index()
    df = df[["open", "high", "low", "close", "volume"]]
    return df


# ── MT5 source ───────────────────────────────────────────────────────────────

def _fetch_from_mt5(symbol: str, timeframe: str, date_from: str, date_to: str) -> pd.DataFrame:
    """Download historical bars from a running MT5 terminal (Windows only)."""
    try:
        import MetaTrader5 as mt5
    except ImportError:
        raise RuntimeError(
            "MetaTrader5 library not available.\n"
            "On Mac/Linux use --source yfinance or set MT5_BRIDGE_URL for bridge mode."
        )
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
    return df[["open", "high", "low", "close", "volume"]]


# ── yfinance source ───────────────────────────────────────────────────────────

def _fetch_from_yfinance(symbol: str, timeframe: str, date_from: str, date_to: str) -> pd.DataFrame:
    """Download data from Yahoo Finance (Mac/Linux friendly)."""
    try:
        import yfinance as yf
    except ImportError:
        raise RuntimeError("yfinance not installed. Run: pip install yfinance")

    from datetime import datetime, timedelta

    yf_symbol = _YF_SYMBOL.get(symbol.upper())
    if yf_symbol is None:
        # Try direct (e.g. 'EURUSD=X' passed directly)
        yf_symbol = symbol

    interval = _YF_INTERVAL.get(timeframe)
    if interval is None:
        raise ValueError(f"Unsupported timeframe for yfinance: {timeframe}")

    # Warn if requested range exceeds yfinance intraday limit
    max_days = _YF_MAX_DAYS.get(timeframe, 9999)
    requested_days = (datetime.fromisoformat(date_to) - datetime.fromisoformat(date_from)).days
    if requested_days > max_days:
        effective_from = (datetime.fromisoformat(date_to) - timedelta(days=max_days)).strftime("%Y-%m-%d")
        print(f"  [yfinance] ⚠  {timeframe} limited to {max_days} days of history. "
              f"Using {effective_from} → {date_to}")
        date_from = effective_from

    ticker = yf.Ticker(yf_symbol)
    df = ticker.history(start=date_from, end=date_to, interval=interval, auto_adjust=True)

    if df.empty:
        raise RuntimeError(
            f"No data returned from yfinance for {yf_symbol} ({interval}).\n"
            f"Note: intraday data (M15/H1) is limited to recent history."
        )

    df = df.rename(columns={"Open": "open", "High": "high",
                             "Low": "low", "Close": "close", "Volume": "volume"})
    df = df[["open", "high", "low", "close", "volume"]]
    df.index = pd.to_datetime(df.index, utc=True)
    df.index.name = "time"
    return df.sort_index()


# ── MT5 Bridge source ─────────────────────────────────────────────────────────

def _fetch_from_bridge(symbol: str, timeframe: str, date_from: str, date_to: str) -> pd.DataFrame:
    """
    Fetch data from a remote MT5 bridge server (mt5_bridge/server.py).
    Set env var MT5_BRIDGE_URL to the server address, e.g.:
        export MT5_BRIDGE_URL=http://192.168.1.100:5000
    """
    try:
        import requests
    except ImportError:
        raise RuntimeError("requests not installed. Run: pip install requests")

    base_url = os.environ.get("MT5_BRIDGE_URL", "http://localhost:5000").rstrip("/")
    url = f"{base_url}/ohlcv"
    params = {"symbol": symbol, "tf": timeframe, "from": date_from, "to": date_to}

    headers = {}
    token = os.environ.get("MT5_BRIDGE_TOKEN", "")
    if token:
        headers["Authorization"] = f"Bearer {token}"

    try:
        resp = requests.get(url, params=params, headers=headers, timeout=60)
        resp.raise_for_status()
    except Exception as e:
        raise RuntimeError(
            f"MT5 bridge request failed: {e}\n"
            f"Make sure mt5_bridge/server.py is running on {base_url}"
        )

    data = resp.json()
    df = pd.DataFrame(data)
    df["time"] = pd.to_datetime(df["time"], utc=True)
    df = df.set_index("time")[["open", "high", "low", "close", "volume"]]
    return df.sort_index()
