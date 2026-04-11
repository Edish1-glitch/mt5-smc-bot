"""
backtest/signal_cache.py — Cache for the expensive signal pre-computation step.

The engine spends most of its cold-path time in detect_bos() / detect_sweeps() /
detect_fvg() over the full M15 history. These results only depend on
(symbol, date_from, date_to, swing_n_ltf, swing_n_htf) — they do NOT depend on
risk parameters, RR, hour filters, etc.

By caching them separately from the trade list, we can change risk/RR/filter
knobs and have a "warm" path that skips the heavy signal scan entirely.
"""

from __future__ import annotations
import hashlib
import pickle
from pathlib import Path
from typing import Optional

CACHE_DIR = Path(__file__).parent.parent / "data" / "cache" / "signals"
CACHE_DIR.mkdir(parents=True, exist_ok=True)


def _make_key(symbol: str, date_from: str, date_to: str,
              swing_n_ltf: int, swing_n_htf: int) -> str:
    raw = f"{symbol.upper()}|{date_from}|{date_to}|{swing_n_ltf}|{swing_n_htf}"
    h   = hashlib.sha1(raw.encode()).hexdigest()[:12]
    return f"{symbol.upper()}_{date_from}_{date_to}_n{swing_n_ltf}-{swing_n_htf}_{h}"


def get(symbol: str, date_from: str, date_to: str,
        swing_n_ltf: int, swing_n_htf: int) -> Optional[dict]:
    """Return cached signals dict, or None on miss.

    Cached dict keys: full_bos, full_sweeps, h1_bos, fvgs (with mit_idx
    pre-computed)."""
    key = _make_key(symbol, date_from, date_to, swing_n_ltf, swing_n_htf)
    path = CACHE_DIR / f"{key}.pkl"
    if not path.exists():
        return None
    try:
        with open(path, "rb") as f:
            return pickle.load(f)
    except Exception:
        path.unlink(missing_ok=True)
        return None


def put(symbol: str, date_from: str, date_to: str,
        swing_n_ltf: int, swing_n_htf: int, signals: dict) -> None:
    key = _make_key(symbol, date_from, date_to, swing_n_ltf, swing_n_htf)
    path = CACHE_DIR / f"{key}.pkl"
    try:
        with open(path, "wb") as f:
            pickle.dump(signals, f, protocol=pickle.HIGHEST_PROTOCOL)
    except Exception:
        pass


def clear() -> int:
    count = 0
    for f in CACHE_DIR.glob("*.pkl"):
        f.unlink()
        count += 1
    return count
