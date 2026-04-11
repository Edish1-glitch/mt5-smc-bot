"""
backtest/history.py — Append-only JSONL log of all backtest runs.

Each line is a single run record:
  {
    "run_id": "EURUSD_2024-04-11_2026-04-11_a1b2c3d4",
    "timestamp": "2026-04-11T15:30:00",
    "symbol": "EURUSD",
    "date_from": "2024-04-11",
    "date_to": "2026-04-11",
    "params": { ... },
    "stats": { "total_trades": 316, "win_rate_pct": 44.94, ... }
  }

History is kept forever. The /api/history endpoint reads this file (newest
first), and the /api/history/{run_id} endpoint loads the corresponding pickle
from results_cache.
"""

from __future__ import annotations
import json
from datetime import datetime
from pathlib import Path
from typing import Optional

HISTORY_FILE = Path(__file__).parent.parent / "data" / "cache" / "backtest_results" / "_history.jsonl"
HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)


def append(run_id: str, symbol: str, date_from: str, date_to: str,
           params: dict, stats: dict) -> None:
    """Append a new run record. Silently ignores I/O errors."""
    record = {
        "run_id":    run_id,
        "timestamp": datetime.utcnow().isoformat(timespec="seconds"),
        "symbol":    symbol,
        "date_from": date_from,
        "date_to":   date_to,
        "params":    params,
        "stats":     stats,
    }
    try:
        with open(HISTORY_FILE, "a") as f:
            f.write(json.dumps(record, default=str) + "\n")
    except Exception:
        pass


def list_all(limit: Optional[int] = None) -> list[dict]:
    """Return all history records, newest first. Optional limit."""
    if not HISTORY_FILE.exists():
        return []
    records = []
    try:
        with open(HISTORY_FILE) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    records.append(json.loads(line))
                except Exception:
                    continue
    except Exception:
        return []
    records.reverse()  # newest first
    if limit:
        records = records[:limit]
    return records


def find(run_id: str) -> Optional[dict]:
    """Return a single history record by run_id."""
    for r in list_all():
        if r.get("run_id") == run_id:
            return r
    return None


def remove(run_id: str) -> bool:
    """Delete a run from the history file. Returns True if removed."""
    if not HISTORY_FILE.exists():
        return False
    kept = []
    removed = False
    try:
        with open(HISTORY_FILE) as f:
            for line in f:
                line_s = line.strip()
                if not line_s:
                    continue
                try:
                    rec = json.loads(line_s)
                except Exception:
                    continue
                if rec.get("run_id") == run_id:
                    removed = True
                    continue
                kept.append(line_s)
    except Exception:
        return False
    if removed:
        try:
            with open(HISTORY_FILE, "w") as f:
                f.write("\n".join(kept) + ("\n" if kept else ""))
        except Exception:
            return False
    return removed
