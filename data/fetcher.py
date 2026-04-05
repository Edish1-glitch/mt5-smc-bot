"""
data/fetcher.py — Historical OHLCV data download and caching.

Sources (selected automatically or via --source flag):
  'mt5'      — MetaTrader5 Python lib (Windows only, MT5 must be running)
  'oanda'    — OANDA v20 REST API (חינם לגמרי, חשבון דמו, שנים של נתונים)
                 הגדרה ב-2 דקות → https://www.oanda.com/register/#/sign-up/demo
                 export OANDA_TOKEN=<api-token>
                 export OANDA_ACCOUNT_ID=<account-id>   ← אופציונלי
  'yfinance' — Yahoo Finance (ללא הגדרה, M15=60 יום / H1=730 יום)
  'bridge'   — MT5 REST bridge (mt5_bridge/server.py על Windows)
                 export MT5_BRIDGE_URL=http://<host>:5000

Auto-detection:
  oanda (if OANDA_TOKEN set) → bridge (if MT5_BRIDGE_URL set)
  → mt5 (Windows) → yfinance

Usage:
    df = get_ohlcv("EURUSD", "H1", "2020-01-01", "2024-01-01")
    df = get_ohlcv("EURUSD", "M15", "2023-01-01", "2024-01-01", source="oanda")
"""

import os
import platform
import pandas as pd
from pathlib import Path
from datetime import datetime, timezone, timedelta

CACHE_DIR = Path(__file__).parent / "cache"
CACHE_DIR.mkdir(exist_ok=True)

# ── MT5 timeframe → integer ───────────────────────────────────────────────────
_MT5_TF = {
    "M1": 1, "M5": 5, "M15": 15, "M30": 30,
    "H1": 16385, "H4": 16388, "D1": 16408,
}

# ── OANDA symbol mapping (MT5 name → OANDA instrument) ───────────────────────
_OANDA_SYMBOL = {
    "EURUSD": "EUR_USD", "GBPUSD": "GBP_USD", "USDJPY": "USD_JPY",
    "USDCHF": "USD_CHF", "AUDUSD": "AUD_USD", "USDCAD": "USD_CAD",
    "NZDUSD": "NZD_USD", "EURGBP": "EUR_GBP", "EURJPY": "EUR_JPY",
    "GBPJPY": "GBP_JPY", "XAUUSD": "XAU_USD", "XAGUSD": "XAG_USD",
    "BTCUSD": "BTC_USD", "NAS100": "NAS100_USD", "US500":  "SPX500_USD",
    "US30":   "US30_USD",
}

# ── OANDA granularity mapping (MT5 TF → OANDA granularity) ───────────────────
_OANDA_GRAN = {
    "M1": "M1", "M5": "M5", "M15": "M15", "M30": "M30",
    "H1": "H1", "H4": "H4", "D1":  "D",
}

# ── yfinance symbol + interval maps ──────────────────────────────────────────
_YF_SYMBOL = {
    "EURUSD": "EURUSD=X", "GBPUSD": "GBPUSD=X", "USDJPY": "USDJPY=X",
    "USDCHF": "USDCHF=X", "AUDUSD": "AUDUSD=X", "USDCAD": "USDCAD=X",
    "NZDUSD": "NZDUSD=X", "XAUUSD": "GC=F",     "NAS100": "NQ=F",
    "US500":  "ES=F",     "US30":   "YM=F",      "BTCUSD": "BTC-USD",
}
_YF_INTERVAL = {
    "M1": "1m", "M5": "5m", "M15": "15m", "M30": "30m",
    "H1": "1h", "H4": "4h", "D1":  "1d",
}
_YF_MAX_DAYS = {
    "M1": 7, "M5": 60, "M15": 60, "M30": 60,
    "H1": 730, "H4": 730, "D1": 9999,
}


# ── Auto-detect ───────────────────────────────────────────────────────────────

def _detect_source() -> str:
    if os.environ.get("OANDA_TOKEN"):
        return "oanda"
    if os.environ.get("MT5_BRIDGE_URL"):
        return "bridge"
    if platform.system() == "Windows":
        return "mt5"
    return "yfinance"


# ── Public API ────────────────────────────────────────────────────────────────

def get_ohlcv(
    symbol: str,
    timeframe: str,
    date_from: str,
    date_to: str,
    source: str = "auto",
) -> pd.DataFrame:
    """
    Return OHLCV DataFrame (columns: open high low close volume, UTC DatetimeIndex).

    Parameters
    ----------
    symbol    : MT5-style name, e.g. 'EURUSD', 'XAUUSD', 'NAS100'
    timeframe : 'M1' 'M5' 'M15' 'M30' 'H1' 'H4' 'D1'
    date_from : 'YYYY-MM-DD'
    date_to   : 'YYYY-MM-DD'
    source    : 'auto' | 'oanda' | 'yfinance' | 'mt5' | 'bridge'
    """
    if source == "auto":
        source = _detect_source()

    cache_path = CACHE_DIR / f"{symbol}_{timeframe}_{date_from}_{date_to}_{source}.parquet"
    if cache_path.exists():
        return pd.read_parquet(cache_path)

    fetchers = {
        "mt5":      _fetch_from_mt5,
        "oanda":    _fetch_from_oanda,
        "yfinance": _fetch_from_yfinance,
        "bridge":   _fetch_from_bridge,
    }
    if source not in fetchers:
        raise ValueError(f"Unknown source {source!r}. Options: {list(fetchers)}")

    df = fetchers[source](symbol, timeframe, date_from, date_to)
    df.to_parquet(cache_path)
    return df


def load_from_csv(csv_path: str, symbol: str = "", timeframe: str = "") -> pd.DataFrame:
    """Load OHLCV from an MT5-exported CSV (columns: time,open,high,low,close,tick_volume)."""
    df = pd.read_csv(csv_path, parse_dates=["time"])
    df = df.rename(columns={"tick_volume": "volume"})
    return df.set_index("time").sort_index()[["open", "high", "low", "close", "volume"]]


# ── MT5 (Windows) ────────────────────────────────────────────────────────────

def _fetch_from_mt5(symbol, timeframe, date_from, date_to):
    try:
        import MetaTrader5 as mt5
    except ImportError:
        raise RuntimeError(
            "MetaTrader5 requires Windows.\n"
            "On Mac use --source oanda  (free demo account at oanda.com)"
        )
    if not mt5.initialize():
        raise RuntimeError(f"MT5 initialize() failed: {mt5.last_error()}")
    tf = _MT5_TF.get(timeframe)
    if not tf:
        raise ValueError(f"Unknown timeframe: {timeframe}")
    dt_from = datetime.fromisoformat(date_from).replace(tzinfo=timezone.utc)
    dt_to   = datetime.fromisoformat(date_to).replace(tzinfo=timezone.utc)
    rates = mt5.copy_rates_range(symbol, tf, dt_from, dt_to)
    mt5.shutdown()
    if rates is None or len(rates) == 0:
        raise RuntimeError(f"No data for {symbol} {timeframe}")
    df = pd.DataFrame(rates)
    df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
    return df.set_index("time").rename(columns={"tick_volume": "volume"})[
        ["open", "high", "low", "close", "volume"]
    ]


# ── OANDA (free demo, years of history) ──────────────────────────────────────

def _fetch_from_oanda(symbol, timeframe, date_from, date_to):
    """
    Download from OANDA v20 REST API.

    הגדרה חד-פעמית (2 דקות, חינם לגמרי):
      1. צור חשבון דמו חינמי:  https://www.oanda.com/register/#/sign-up/demo
      2. My Account → Manage API Access → Generate token
      3. העתק את Account ID מ-Dashboard
      4. הגדר:
            export OANDA_TOKEN=<your-api-token>
            export OANDA_ACCOUNT_ID=<your-account-id>  ← אופציונלי, לנתוני שוק לא נדרש
      5. הרץ:
            python main.py --symbol EURUSD --from 2023-01-01 --to 2024-01-01
    """
    try:
        import requests
    except ImportError:
        raise RuntimeError("requests not installed: pip install requests")

    token = os.environ.get("OANDA_TOKEN", "")
    if not token:
        raise RuntimeError(
            "OANDA_TOKEN לא הוגדר.\n\n"
            "הגדרה חינמית ב-2 דקות:\n"
            "  1. https://www.oanda.com/register/#/sign-up/demo\n"
            "  2. My Account → Manage API Access → Generate token\n"
            "  3. export OANDA_TOKEN=<token>\n"
            "  4. python main.py --symbol EURUSD --from 2023-01-01 --to 2024-01-01"
        )

    instrument = _OANDA_SYMBOL.get(symbol.upper(), symbol)
    gran       = _OANDA_GRAN.get(timeframe)
    if not gran:
        raise ValueError(f"Unsupported timeframe for OANDA: {timeframe}")

    # Detect practice vs live token (practice tokens start with different prefix)
    base_url = "https://api-fxpractice.oanda.com/v3"  # demo account
    headers  = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    dt_from = datetime.fromisoformat(date_from).replace(tzinfo=timezone.utc)
    dt_to   = datetime.fromisoformat(date_to).replace(tzinfo=timezone.utc)

    all_candles = []
    current = dt_from
    batch_size = 4000  # OANDA max per request

    print(f"  [OANDA] Downloading {symbol} {timeframe} {date_from} → {date_to} ...")

    while current < dt_to:
        params = {
            "granularity": gran,
            "from": current.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "to":   min(dt_to, current + _oanda_chunk_delta(timeframe, batch_size))
                    .strftime("%Y-%m-%dT%H:%M:%SZ"),
            "price": "M",  # Mid prices
            "count": batch_size,
        }
        resp = requests.get(
            f"{base_url}/instruments/{instrument}/candles",
            headers=headers, params=params, timeout=30,
        )

        if resp.status_code == 401:
            raise RuntimeError(
                "OANDA token invalid or expired.\n"
                "Check OANDA_TOKEN — use practice token for demo accounts."
            )
        resp.raise_for_status()

        candles = resp.json().get("candles", [])
        if not candles:
            break

        # only take complete candles
        candles = [c for c in candles if c.get("complete", True)]
        all_candles.extend(candles)

        last_ts = datetime.fromisoformat(candles[-1]["time"].replace("Z", "+00:00"))
        if last_ts <= current:
            break
        current = last_ts + timedelta(seconds=1)
        print(f"    ...{len(all_candles):,} bars, up to {last_ts.date()}")

    if not all_candles:
        raise RuntimeError(f"No data returned from OANDA for {instrument} {gran}")

    rows = []
    for c in all_candles:
        m = c["mid"]
        rows.append({
            "time":   pd.to_datetime(c["time"], utc=True),
            "open":   float(m["o"]),
            "high":   float(m["h"]),
            "low":    float(m["l"]),
            "close":  float(m["c"]),
            "volume": int(c.get("volume", 0)),
        })

    df = pd.DataFrame(rows).set_index("time").sort_index()
    return df[date_from:date_to]


def _oanda_chunk_delta(timeframe: str, count: int) -> timedelta:
    """Estimate timedelta for `count` bars of the given timeframe."""
    minutes = {"M1": 1, "M5": 5, "M15": 15, "M30": 30,
               "H1": 60, "H4": 240, "D1": 1440}.get(timeframe, 60)
    return timedelta(minutes=minutes * count * 1.5)  # 1.5× buffer for weekends


# ── yfinance (fallback, no setup needed) ─────────────────────────────────────

def _fetch_from_yfinance(symbol, timeframe, date_from, date_to):
    try:
        import yfinance as yf
    except ImportError:
        raise RuntimeError("pip install yfinance")

    yf_sym   = _YF_SYMBOL.get(symbol.upper(), symbol)
    interval = _YF_INTERVAL.get(timeframe)
    if not interval:
        raise ValueError(f"Unsupported timeframe for yfinance: {timeframe}")

    max_days = _YF_MAX_DAYS.get(timeframe, 9999)
    req_days = (datetime.fromisoformat(date_to) - datetime.fromisoformat(date_from)).days
    if req_days > max_days:
        eff_from = (datetime.fromisoformat(date_to) - timedelta(days=max_days)).strftime("%Y-%m-%d")
        print(f"  [yfinance] ⚠  {timeframe} limited to {max_days} days → using {eff_from}")
        date_from = eff_from

    df = yf.Ticker(yf_sym).history(start=date_from, end=date_to,
                                    interval=interval, auto_adjust=True)
    if df.empty:
        raise RuntimeError(f"No yfinance data for {yf_sym} {interval}")

    df = df.rename(columns={"Open": "open", "High": "high",
                             "Low": "low",  "Close": "close", "Volume": "volume"})
    df = df[["open", "high", "low", "close", "volume"]]
    df.index = pd.to_datetime(df.index, utc=True)
    df.index.name = "time"
    return df.sort_index()


# ── MT5 Bridge ────────────────────────────────────────────────────────────────

def _fetch_from_bridge(symbol, timeframe, date_from, date_to):
    try:
        import requests
    except ImportError:
        raise RuntimeError("pip install requests")

    base = os.environ.get("MT5_BRIDGE_URL", "http://localhost:5000").rstrip("/")
    hdrs = {}
    tok  = os.environ.get("MT5_BRIDGE_TOKEN", "")
    if tok:
        hdrs["Authorization"] = f"Bearer {tok}"

    resp = requests.get(f"{base}/ohlcv",
                        params={"symbol": symbol, "tf": timeframe,
                                "from": date_from, "to": date_to},
                        headers=hdrs, timeout=60)
    resp.raise_for_status()
    df = pd.DataFrame(resp.json())
    df["time"] = pd.to_datetime(df["time"], utc=True)
    return df.set_index("time")[["open", "high", "low", "close", "volume"]].sort_index()
