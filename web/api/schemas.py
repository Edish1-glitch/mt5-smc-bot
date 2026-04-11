"""
web/api/schemas.py — Pydantic models for the FastAPI request/response payloads.
"""

from __future__ import annotations
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field


class BacktestRequest(BaseModel):
    symbol: str = Field(..., examples=["EURUSD"])
    date_from: str = Field(..., examples=["2024-04-11"])
    date_to:   str = Field(..., examples=["2026-04-11"])

    # Risk
    initial_capital: float = 100_000
    risk_per_trade:  float = 500
    compound:        bool  = False
    risk_pct:        float = 0.5

    # RR
    rr: float = 3.0

    # Filters
    min_fib_span:       Optional[float] = None  # None = use per-symbol default
    entry_buffer:       Optional[float] = None
    require_fvg:        bool = False
    swing_n_ltf:        int  = 3
    swing_n_htf:        int  = 3

    # Post-hoc filters
    hours_filter_start: int = 0          # Israel hour, inclusive
    hours_filter_end:   int = 23
    weekday_mask:       int = 0b0111111  # bit i = weekday i (Sun=0..Sat=6); default Sun-Fri
    max_trades_per_day: int = 0          # 0 = unlimited

    # Cost
    commission_per_lot: float = 0.0


class TradeJson(BaseModel):
    direction:    str
    entry_price:  float
    sl_price:     float
    tp_price:     float
    entry_time:   str
    exit_time:    Optional[str]
    exit_price:   Optional[float]
    result:       Optional[str]
    pnl_usd:      float
    risk_usd:     float
    lot_size:     float
    impulse_high: float
    impulse_low:  float
    impulse_high_time: Optional[str]
    impulse_low_time:  Optional[str]


class BacktestResult(BaseModel):
    run_id:        str
    symbol:        str
    date_from:     str
    date_to:       str
    stats:         Dict[str, Any]
    trades:        List[TradeJson]
    equity_curve:  List[Dict[str, Any]]   # [{time, equity}, ...]
    params:        Dict[str, Any]
    cached:        bool


class HistoryRecord(BaseModel):
    run_id:    str
    timestamp: str
    symbol:    str
    date_from: str
    date_to:   str
    params:    Dict[str, Any]
    stats:     Dict[str, Any]


class JobStatus(BaseModel):
    job_id:    str
    state:     str         # "queued" | "running" | "done" | "error"
    phase:     str         # "data" | "signals" | "engine" | "done"
    progress:  float       # 0..1
    n_trades:  int
    eta_sec:   float
    error:     Optional[str] = None
    run_id:    Optional[str] = None
