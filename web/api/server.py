"""
web/api/server.py — FastAPI backend for the SMC backtest dashboard.

Run with:
    uvicorn web.api.server:app --port 8000 --host 0.0.0.0
"""

from __future__ import annotations
import asyncio
import json
import sys
import threading
import time
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sse_starlette.sse import EventSourceResponse

# Make project root importable
ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT))

import config
from data.fetcher import get_ohlcv
from backtest.engine import run_backtest, precompute_signals
from backtest.results import compute_stats
from backtest import results_cache, signal_cache, history
from backtest.trade import Trade

from web.api.schemas import BacktestRequest, BacktestResult, HistoryRecord
from web.api import jobs


app = FastAPI(title="SMC Backtest API", version="1.0")


# ── Static frontend ──────────────────────────────────────────────────────────
STATIC_DIR = Path(__file__).parent.parent / "static"
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/")
def index():
    idx = STATIC_DIR / "index.html"
    if idx.exists():
        return FileResponse(str(idx))
    return JSONResponse({"error": "index.html not found"}, status_code=404)


@app.get("/manifest.webmanifest")
def manifest():
    f = STATIC_DIR / "manifest.webmanifest"
    return FileResponse(str(f), media_type="application/manifest+json") if f.exists() else JSONResponse({}, status_code=404)


@app.get("/sw.js")
def service_worker():
    f = STATIC_DIR / "sw.js"
    return FileResponse(str(f), media_type="application/javascript") if f.exists() else JSONResponse({}, status_code=404)


# ── Reference endpoints ──────────────────────────────────────────────────────

@app.get("/api/symbols")
def api_symbols():
    return {"symbols": config.SYMBOLS}


@app.get("/api/defaults")
def api_defaults():
    """Default form values for the UI to pre-populate."""
    return {
        "symbol":             "EURUSD",
        "initial_capital":    config.INITIAL_CAPITAL,
        "risk_per_trade":     config.RISK_PER_TRADE,
        "compound":           False,
        "risk_pct":           0.5,
        "rr":                 3.0,
        "swing_n_ltf":        3,
        "swing_n_htf":        3,
        "require_fvg":        config.REQUIRE_FVG,
        "hours_filter_start": 0,
        "hours_filter_end":   23,
        "weekday_mask":       0b0111111,  # Sun-Fri
        "max_trades_per_day": 0,
        "commission_per_lot": 0.0,
    }


# ── Helpers ──────────────────────────────────────────────────────────────────

def _trade_to_json(t: Trade) -> dict:
    return {
        "direction":   t.direction,
        "entry_price": float(t.entry_price),
        "sl_price":    float(t.sl_price),
        "tp_price":    float(t.tp_price),
        "entry_time":  t.entry_time.isoformat() if t.entry_time is not None else None,
        "exit_time":   t.exit_time.isoformat() if t.exit_time  is not None else None,
        "exit_price":  float(t.exit_price) if t.exit_price is not None else None,
        "result":      t.result,
        "pnl_usd":     float(t.pnl_usd),
        "risk_usd":    float(t.risk_usd),
        "lot_size":    float(t.lot_size),
        "impulse_high": float(t.impulse_high),
        "impulse_low":  float(t.impulse_low),
        "impulse_high_time": t.impulse_high_time.isoformat() if t.impulse_high_time is not None else None,
        "impulse_low_time":  t.impulse_low_time.isoformat() if t.impulse_low_time is not None else None,
    }


def _equity_curve_json(trades: list, initial_capital: float) -> list:
    closed = sorted([t for t in trades if t.result in ("win", "loss")],
                    key=lambda t: t.exit_time)
    if not closed:
        return []
    pts = [{"time": closed[0].entry_time.isoformat(), "equity": initial_capital}]
    eq = initial_capital
    for t in closed:
        eq += float(t.pnl_usd)
        pts.append({"time": t.exit_time.isoformat(), "equity": round(eq, 2)})
    return pts


def _params_dict(req: BacktestRequest) -> dict:
    """Canonical params dict used for cache keys + history records."""
    return {
        "risk_per_trade":     req.risk_per_trade,
        "initial_capital":    req.initial_capital,
        "compound":           req.compound,
        "risk_pct":           req.risk_pct,
        "rr":                 req.rr,
        "min_fib_span":       req.min_fib_span,
        "entry_buffer":       req.entry_buffer,
        "require_fvg":        req.require_fvg,
        "swing_n_ltf":        req.swing_n_ltf,
        "swing_n_htf":        req.swing_n_htf,
        "hours_filter":       [req.hours_filter_start, req.hours_filter_end],
        "weekday_mask":       req.weekday_mask,
        "max_trades_per_day": req.max_trades_per_day,
        "commission_per_lot": req.commission_per_lot,
    }


def _weekday_set_from_mask(mask: int) -> set:
    return {i for i in range(7) if mask & (1 << i)}


# ── Background worker ────────────────────────────────────────────────────────

def _run_backtest_job(job_id: str, req: BacktestRequest) -> None:
    try:
        params = _params_dict(req)

        # 1. Try the trade-list cache first
        jobs.update_job(job_id, state="running", phase="results-cache")
        cached = results_cache.get(req.symbol, req.date_from, req.date_to, params)
        if cached is not None:
            jobs.update_job(job_id, phase="data")
            m15 = get_ohlcv(req.symbol, "M15", req.date_from, req.date_to)
            stats = compute_stats(cached, req.initial_capital)
            run_id = results_cache.make_run_id(req.symbol, req.date_from, req.date_to, params)
            result = {
                "run_id":       run_id,
                "symbol":       req.symbol,
                "date_from":    req.date_from,
                "date_to":      req.date_to,
                "stats":        stats,
                "trades":       [_trade_to_json(t) for t in cached],
                "equity_curve": _equity_curve_json(cached, req.initial_capital),
                "params":       params,
                "cached":       True,
            }
            jobs.finish_job(job_id, result, run_id)
            return

        # 2. Load OHLCV (cached on disk via parquet)
        jobs.update_job(job_id, phase="data")
        m15 = get_ohlcv(req.symbol, "M15", req.date_from, req.date_to)
        h1  = get_ohlcv(req.symbol, "H1",  req.date_from, req.date_to)
        if m15 is None or len(m15) < 50:
            jobs.fail_job(job_id, "Not enough M15 data — try a wider date range")
            return

        # 3. Try the signal cache
        jobs.update_job(job_id, phase="signals")
        sigs = signal_cache.get(req.symbol, req.date_from, req.date_to,
                                 req.swing_n_ltf, req.swing_n_htf)
        if sigs is None:
            sigs = precompute_signals(m15, h1,
                                       swing_n_ltf=req.swing_n_ltf,
                                       swing_n_htf=req.swing_n_htf)
            signal_cache.put(req.symbol, req.date_from, req.date_to,
                             req.swing_n_ltf, req.swing_n_htf, sigs)

        # 4. Run the engine
        jobs.update_job(job_id, phase="engine")
        weekdays = _weekday_set_from_mask(req.weekday_mask)
        trades = run_backtest(
            m15, h1, req.symbol,
            risk_per_trade  = req.risk_per_trade,
            compound        = req.compound,
            initial_capital = req.initial_capital,
            risk_pct        = req.risk_pct,
            rr              = req.rr,
            require_fvg     = req.require_fvg,
            min_fib_span    = req.min_fib_span,
            entry_buffer    = req.entry_buffer,
            hours_filter    = (req.hours_filter_start, req.hours_filter_end),
            weekday_filter  = weekdays,
            max_trades_per_day = req.max_trades_per_day,
            commission_per_lot = req.commission_per_lot,
            precomputed     = sigs,
            progress_callback = lambda f, n, e: jobs.set_progress(job_id, f, n, e),
        )

        # 5. Stats + cache + history
        stats = compute_stats(trades, req.initial_capital)
        run_id = results_cache.put(req.symbol, req.date_from, req.date_to, params, trades)
        history.append(run_id, req.symbol, req.date_from, req.date_to, params, stats)

        result = {
            "run_id":       run_id,
            "symbol":       req.symbol,
            "date_from":    req.date_from,
            "date_to":      req.date_to,
            "stats":        stats,
            "trades":       [_trade_to_json(t) for t in trades],
            "equity_curve": _equity_curve_json(trades, req.initial_capital),
            "params":       params,
            "cached":       False,
        }
        jobs.finish_job(job_id, result, run_id)

    except Exception as e:
        import traceback
        traceback.print_exc()
        jobs.fail_job(job_id, str(e))


# ── Backtest endpoints ───────────────────────────────────────────────────────

@app.post("/api/backtest")
async def api_run_backtest(req: BacktestRequest):
    job_id = jobs.create_job()
    threading.Thread(target=_run_backtest_job, args=(job_id, req), daemon=True).start()
    return {"job_id": job_id}


@app.get("/api/backtest/{job_id}/status")
def api_job_status(job_id: str):
    j = jobs.get_job(job_id)
    if j is None:
        raise HTTPException(404, "job not found")
    return jobs.public_view(j)


@app.get("/api/backtest/{job_id}/result")
def api_job_result(job_id: str):
    j = jobs.get_job(job_id)
    if j is None:
        raise HTTPException(404, "job not found")
    if j["state"] != "done":
        raise HTTPException(409, f"job not done (state={j['state']})")
    return j["result"]


@app.get("/api/backtest/{job_id}/stream")
async def api_job_stream(job_id: str, request: Request):
    """Server-Sent Events stream pushing job status updates until done."""
    async def event_gen():
        last_payload = None
        while True:
            if await request.is_disconnected():
                break
            j = jobs.get_job(job_id)
            if j is None:
                yield {"event": "error", "data": json.dumps({"error": "job not found"})}
                break
            payload = {
                "state":    j["state"],
                "phase":    j["phase"],
                "progress": j["progress"],
                "n_trades": j["n_trades"],
                "eta_sec":  j["eta_sec"],
                "error":    j.get("error"),
            }
            if payload != last_payload:
                yield {"event": "progress", "data": json.dumps(payload)}
                last_payload = payload
            if j["state"] == "done":
                yield {"event": "done", "data": json.dumps(j["result"])}
                break
            if j["state"] == "error":
                yield {"event": "error", "data": json.dumps({"error": j.get("error")})}
                break
            await asyncio.sleep(0.3)
    return EventSourceResponse(event_gen())


# ── History endpoints ────────────────────────────────────────────────────────

@app.get("/api/history")
def api_history(limit: int = 100):
    return {"runs": history.list_all(limit=limit)}


@app.get("/api/history/{run_id}")
def api_history_get(run_id: str):
    rec = history.find(run_id)
    if rec is None:
        raise HTTPException(404, "run not found")
    trades = results_cache.get_by_id(run_id)
    if trades is None:
        raise HTTPException(404, "trade list not in cache")
    initial_capital = rec.get("params", {}).get("initial_capital", 100_000)
    return {
        "run_id":       run_id,
        "symbol":       rec["symbol"],
        "date_from":    rec["date_from"],
        "date_to":      rec["date_to"],
        "stats":        rec["stats"],
        "trades":       [_trade_to_json(t) for t in trades],
        "equity_curve": _equity_curve_json(trades, initial_capital),
        "params":       rec["params"],
        "cached":       True,
    }


@app.delete("/api/history/{run_id}")
def api_history_delete(run_id: str):
    history.remove(run_id)
    results_cache.delete(run_id)
    return {"deleted": run_id}
