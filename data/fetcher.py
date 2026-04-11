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
from typing import Optional

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

def _detect_source(timeframe: str = "", date_from: str = "", date_to: str = "") -> str:
    if os.environ.get("OANDA_TOKEN"):
        return "oanda"
    if os.environ.get("MT5_BRIDGE_URL"):
        return "bridge"
    if platform.system() == "Windows":
        return "mt5"
    # yfinance M15 is limited to ~60 days; use Dukascopy for longer ranges
    if date_from and date_to and timeframe:
        max_days = _YF_MAX_DAYS.get(timeframe, 9999)
        try:
            days_requested = (datetime.fromisoformat(date_to) - datetime.fromisoformat(date_from)).days
        except Exception:
            days_requested = 0
        if days_requested > max_days - 5:
            return "dukascopy"
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
        source = _detect_source(timeframe, date_from, date_to)

    cache_path = CACHE_DIR / f"{symbol}_{timeframe}_{date_from}_{date_to}_{source}.parquet"
    if cache_path.exists():
        return pd.read_parquet(cache_path)

    fetchers = {
        "mt5":        _fetch_from_mt5,
        "oanda":      _fetch_from_oanda,
        "yfinance":   _fetch_from_yfinance,
        "bridge":     _fetch_from_bridge,
        "dukascopy":  _fetch_from_dukascopy,
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
    today    = datetime.now(timezone.utc)
    earliest = (today - timedelta(days=max_days - 2)).strftime("%Y-%m-%d")

    # For intraday data: always use period= instead of start/end (more reliable)
    use_period = max_days < 9999
    if use_period:
        if date_from < earliest:
            print(f"  [yfinance] ⚠  {timeframe} limited to last {max_days} days from today")
        period_str = f"{max_days}d"
    else:
        if date_from < earliest:
            date_from = earliest

    ticker = yf.Ticker(yf_sym)
    if use_period:
        df = ticker.history(period=period_str, interval=interval, auto_adjust=True)
    else:
        df = ticker.history(start=date_from, end=date_to,
                            interval=interval, auto_adjust=True)

    if df.empty:
        raise RuntimeError(
            f"yfinance: no data for {yf_sym} ({interval}).\n"
            f"Forex M15 data is unreliable on Yahoo Finance.\n"
            f"Get a free OANDA demo token (2 min) and run:\n"
            f"  export OANDA_TOKEN=<token>\n"
            f"  python3 main.py --symbol EURUSD --from 2023-01-01 --to 2024-01-01\n"
            f"Register: https://www.oanda.com/register/#/sign-up/demo\n"
            f"Token: https://www.oanda.com/account/api-user-tokens"
        )

    df = df.rename(columns={"Open": "open", "High": "high",
                             "Low": "low",  "Close": "close", "Volume": "volume"})
    df = df[["open", "high", "low", "close", "volume"]]
    df.index = pd.to_datetime(df.index, utc=True)
    df.index.name = "time"
    return df.sort_index()


# ── Dukascopy (free, no API key, bank-quality forex history) ─────────────────

# Price scale: Dukascopy stores prices as integer × point_mult
_DUKA_POINT = {
    "EURUSD": 100_000, "GBPUSD": 100_000, "AUDUSD": 100_000,
    "NZDUSD": 100_000, "USDCAD": 100_000, "USDCHF": 100_000,
    "EURGBP": 100_000, "EURJPY": 1_000,   "GBPJPY": 1_000,
    "USDJPY": 1_000,
    "XAUUSD": 1_000,   "XAGUSD": 1_000,
    "NAS100": 1_000,   "US500":  1_000,    "US30": 1_000,
}

# Mapping from MT5-style symbol → Dukascopy symbol path (for indices/CFDs)
_DUKA_SYMBOL = {
    "NAS100": "USATECHIDXUSD",   # Nasdaq 100 CFD
    "US500":  "USA500IDXUSD",    # S&P 500 CFD
    "US30":   "USA30IDXUSD",     # Dow Jones CFD
    "GER40":  "DEUIDXEUR",       # DAX CFD
    "UK100":  "GBRIDXGBP",       # FTSE 100 CFD
}

# Resample 1-min candles → target timeframe
_DUKA_RESAMPLE = {
    "M1": "1min", "M5": "5min", "M15": "15min", "M30": "30min",
    "H1": "1h",   "H4": "4h",   "D1":  "1D",
}


_DUKA_DAILY_CACHE = CACHE_DIR / "duka_daily"
_DUKA_DAILY_CACHE.mkdir(exist_ok=True)

_DUKA_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/120.0.0.0 Safari/537.36"
}


def _fetch_dukascopy_day(duka_sym: str, day: datetime, mult: int, retries: int = 3) -> Optional[pd.DataFrame]:
    """
    Fetch a single day of 1-minute Dukascopy bars.
    Caches per-day to avoid re-downloads. Returns None if no data for that day.
    Retries failed requests; only caches "real" empty days (weekends/holidays).
    """
    import lzma, struct, requests, time

    cache_file = _DUKA_DAILY_CACHE / f"{duka_sym}_{day.strftime('%Y%m%d')}.parquet"
    if cache_file.exists():
        try:
            df = pd.read_parquet(cache_file)
            return df if len(df) > 0 else None
        except Exception:
            cache_file.unlink(missing_ok=True)

    # Dukascopy months are 0-indexed (Jan=00)
    url = (
        f"https://datafeed.dukascopy.com/datafeed/{duka_sym}/"
        f"{day.year}/{day.month - 1:02d}/{day.day:02d}"
        f"/BID_candles_min_1.bi5"
    )

    last_status = None
    for attempt in range(retries):
        try:
            resp = requests.get(url, headers=_DUKA_HEADERS, timeout=20)
            last_status = resp.status_code
        except Exception:
            time.sleep(0.5 * (attempt + 1))
            continue

        if resp.status_code == 200:
            if not resp.content:
                # Real empty response = weekend/holiday → cache as empty marker
                pd.DataFrame(columns=["open", "high", "low", "close", "volume"]).to_parquet(cache_file)
                return None
            break  # success → process below
        elif resp.status_code == 404:
            # 404 = day not in feed → cache as empty marker
            pd.DataFrame(columns=["open", "high", "low", "close", "volume"]).to_parquet(cache_file)
            return None
        else:
            # 429/503/etc → backoff and retry
            time.sleep(1.0 * (attempt + 1))
    else:
        # All retries exhausted → don't cache, will retry on next run
        return None

    try:
        raw = lzma.decompress(resp.content)
    except Exception:
        return None

    fmt = ">IIIIIf"
    sz  = struct.calcsize(fmt)
    recs = []
    for i in range(0, len(raw) - sz + 1, sz):
        ts_ms, op, hi, lo, cl, vol = struct.unpack_from(fmt, raw, i)
        ts = day + timedelta(seconds=int(ts_ms))
        recs.append((ts, op / mult, hi / mult, lo / mult, cl / mult, vol))

    if not recs:
        pd.DataFrame(columns=["open", "high", "low", "close", "volume"]).to_parquet(cache_file)
        return None

    df_day = pd.DataFrame(recs, columns=["time", "open", "high", "low", "close", "volume"])
    df_day["time"] = pd.DatetimeIndex(pd.to_datetime(df_day["time"], utc=True))
    df_day = df_day.set_index("time")
    df_day.to_parquet(cache_file)
    return df_day


def _fetch_from_dukascopy(symbol, timeframe, date_from, date_to):
    """
    Download free OHLCV data from Dukascopy's public data feed.

    No API key required. Data is bank-quality, goes back 10+ years.
    Downloads 1-minute BID candles (bi5 format) then resamples.
    Uses per-day caching + parallel downloads (30 workers).

    Supported: all major forex pairs + XAUUSD + indices.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed
    import threading

    resample_rule = _DUKA_RESAMPLE.get(timeframe)
    if not resample_rule:
        raise ValueError(f"Unsupported timeframe for Dukascopy: {timeframe}")

    mult = _DUKA_POINT.get(symbol.upper(), 100_000)
    duka_sym = _DUKA_SYMBOL.get(symbol.upper(), symbol.upper())

    dt_from = datetime.fromisoformat(date_from).replace(tzinfo=timezone.utc)
    dt_to   = datetime.fromisoformat(date_to).replace(tzinfo=timezone.utc)

    # Build day list
    days = []
    current = dt_from.replace(hour=0, minute=0, second=0, microsecond=0)
    while current < dt_to:
        days.append(current)
        current += timedelta(days=1)

    total = len(days)
    done = [0]
    lock = threading.Lock()
    frames: list[pd.DataFrame] = []

    def _worker(day):
        df = _fetch_dukascopy_day(duka_sym, day, mult)
        with lock:
            done[0] += 1
            if done[0] % 20 == 0 or done[0] == total:
                pct = done[0] / total * 100
                bars = sum(len(f) for f in frames)
                print(f"\r  [Dukascopy] {pct:4.0f}%  ({done[0]}/{total} days)  bars: {bars:,}   ",
                      end="", flush=True)
        return df

    with ThreadPoolExecutor(max_workers=10) as ex:
        futures = [ex.submit(_worker, d) for d in days]
        for fut in as_completed(futures):
            try:
                df = fut.result()
                if df is not None and len(df) > 0:
                    frames.append(df)
            except Exception:
                pass

    print()  # newline after progress bar

    if not frames:
        raise RuntimeError(
            f"Dukascopy: no data returned for {symbol} "
            f"({date_from} → {date_to}). "
            f"Check symbol name — supported: EURUSD GBPUSD USDJPY XAUUSD etc."
        )

    # Combine all 1-min bars
    m1 = pd.concat(frames).sort_index()
    m1 = m1[~m1.index.duplicated(keep="first")]

    # Resample to target timeframe
    if timeframe == "M1":
        return m1

    agg = {
        "open":   "first",
        "high":   "max",
        "low":    "min",
        "close":  "last",
        "volume": "sum",
    }
    df = m1.resample(resample_rule, label="left", closed="left").agg(agg)
    df = df.dropna(subset=["open"])

    # Filter to requested date range
    return df[date_from:date_to]


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
