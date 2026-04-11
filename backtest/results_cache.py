"""
backtest/results_cache.py — Persistent disk cache for backtest results.

Saves the full Trade list to a pickle file keyed by (symbol, dates, params hash).
Re-runs with identical params return instantly (~10ms) instead of re-running
the engine (~5 minutes for 2 years of M15 data).
"""

from __future__ import annotations
import hashlib
import pickle
from pathlib import Path
from typing import Optional

CACHE_DIR = Path(__file__).parent.parent / "data" / "cache" / "backtest_results"
CACHE_DIR.mkdir(parents=True, exist_ok=True)


def _make_key(
    symbol: str,
    date_from: str,
    date_to: str,
    risk_per_trade: float,
    compound: bool,
    initial_capital: float,
    risk_pct: float,
    extra: str = "",
) -> str:
    """Build a stable cache key from backtest parameters."""
    parts = [
        symbol.upper(),
        date_from,
        date_to,
        f"risk={risk_per_trade}",
        f"compound={compound}",
        f"capital={initial_capital}",
        f"pct={risk_pct}",
        extra,
    ]
    raw = "|".join(parts)
    h   = hashlib.sha1(raw.encode()).hexdigest()[:12]
    return f"{symbol.upper()}_{date_from}_{date_to}_{h}"


def get(
    symbol: str,
    date_from: str,
    date_to: str,
    risk_per_trade: float = 500,
    compound: bool = False,
    initial_capital: float = 100_000,
    risk_pct: float = 0.5,
    extra: str = "",
) -> Optional[list]:
    """Return cached trades list, or None if not cached."""
    key = _make_key(symbol, date_from, date_to, risk_per_trade, compound, initial_capital, risk_pct, extra)
    path = CACHE_DIR / f"{key}.pkl"
    if not path.exists():
        return None
    try:
        with open(path, "rb") as f:
            return pickle.load(f)
    except Exception:
        path.unlink(missing_ok=True)
        return None


def put(
    symbol: str,
    date_from: str,
    date_to: str,
    trades: list,
    risk_per_trade: float = 500,
    compound: bool = False,
    initial_capital: float = 100_000,
    risk_pct: float = 0.5,
    extra: str = "",
) -> None:
    """Save trades list to disk cache."""
    key = _make_key(symbol, date_from, date_to, risk_per_trade, compound, initial_capital, risk_pct, extra)
    path = CACHE_DIR / f"{key}.pkl"
    try:
        with open(path, "wb") as f:
            pickle.dump(trades, f, protocol=pickle.HIGHEST_PROTOCOL)
    except Exception:
        pass


def clear() -> int:
    """Delete all cached results. Returns number of files removed."""
    count = 0
    for f in CACHE_DIR.glob("*.pkl"):
        f.unlink()
        count += 1
    return count
