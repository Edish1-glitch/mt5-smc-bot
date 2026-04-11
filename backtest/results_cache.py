"""
backtest/results_cache.py — Persistent disk cache for backtest results.

Keys are derived from a `params dict` that includes every knob that affects
the trade list. The dict is JSON-serialised then hashed, so adding new knobs
later is easy: just add them to the dict and old keys naturally invalidate.
"""

from __future__ import annotations
import hashlib
import json
import pickle
from pathlib import Path
from typing import Optional

CACHE_DIR = Path(__file__).parent.parent / "data" / "cache" / "backtest_results"
CACHE_DIR.mkdir(parents=True, exist_ok=True)


def _params_hash(params: dict) -> str:
    raw = json.dumps(params, sort_keys=True, default=str)
    return hashlib.sha1(raw.encode()).hexdigest()[:12]


def make_run_id(symbol: str, date_from: str, date_to: str, params: dict) -> str:
    return f"{symbol.upper()}_{date_from}_{date_to}_{_params_hash(params)}"


def _path_for(run_id: str) -> Path:
    return CACHE_DIR / f"{run_id}.pkl"


def get(symbol: str, date_from: str, date_to: str, params: dict) -> Optional[list]:
    """Return cached trades list, or None if not cached."""
    rid = make_run_id(symbol, date_from, date_to, params)
    path = _path_for(rid)
    if not path.exists():
        return None
    try:
        with open(path, "rb") as f:
            return pickle.load(f)
    except Exception:
        path.unlink(missing_ok=True)
        return None


def put(symbol: str, date_from: str, date_to: str, params: dict, trades: list) -> str:
    """Save trades list to disk cache. Returns the run_id."""
    rid = make_run_id(symbol, date_from, date_to, params)
    path = _path_for(rid)
    try:
        with open(path, "wb") as f:
            pickle.dump(trades, f, protocol=pickle.HIGHEST_PROTOCOL)
    except Exception:
        pass
    return rid


def get_by_id(run_id: str) -> Optional[list]:
    path = _path_for(run_id)
    if not path.exists():
        return None
    try:
        with open(path, "rb") as f:
            return pickle.load(f)
    except Exception:
        return None


def delete(run_id: str) -> bool:
    path = _path_for(run_id)
    if path.exists():
        path.unlink()
        return True
    return False


def clear() -> int:
    count = 0
    for f in CACHE_DIR.glob("*.pkl"):
        f.unlink()
        count += 1
    return count
