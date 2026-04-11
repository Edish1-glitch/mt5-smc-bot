"""
web/api/jobs.py — In-memory job table + background worker for backtest runs.

A backtest is run on a single background thread (one at a time is fine for our
single-user case). The HTTP handler creates a job, returns its id, and the
client opens an SSE stream to /api/backtest/{job_id}/stream which polls the
shared dict.
"""

from __future__ import annotations
import threading
import time
import uuid
from typing import Optional, Dict, Any

# Shared state — the SSE handler reads from this
_jobs: Dict[str, Dict[str, Any]] = {}
_lock = threading.Lock()


def create_job() -> str:
    job_id = uuid.uuid4().hex[:12]
    with _lock:
        _jobs[job_id] = {
            "job_id":   job_id,
            "state":    "queued",
            "phase":    "queued",
            "progress": 0.0,
            "n_trades": 0,
            "eta_sec":  0.0,
            "error":    None,
            "result":   None,
            "run_id":   None,
            "created":  time.time(),
        }
    return job_id


def get_job(job_id: str) -> Optional[Dict[str, Any]]:
    with _lock:
        j = _jobs.get(job_id)
        return dict(j) if j else None


def update_job(job_id: str, **fields) -> None:
    with _lock:
        if job_id in _jobs:
            _jobs[job_id].update(fields)


def set_progress(job_id: str, progress: float, n_trades: int, eta_sec: float) -> None:
    update_job(job_id,
               state="running",
               phase="engine",
               progress=progress,
               n_trades=n_trades,
               eta_sec=eta_sec)


def finish_job(job_id: str, result: dict, run_id: str) -> None:
    update_job(job_id,
               state="done",
               phase="done",
               progress=1.0,
               result=result,
               run_id=run_id)


def fail_job(job_id: str, error: str) -> None:
    update_job(job_id,
               state="error",
               phase="error",
               error=error)


def public_view(job: dict) -> dict:
    """Strip internal-only fields before sending to the client."""
    return {
        "job_id":   job["job_id"],
        "state":    job["state"],
        "phase":    job["phase"],
        "progress": job["progress"],
        "n_trades": job["n_trades"],
        "eta_sec":  job["eta_sec"],
        "error":    job.get("error"),
        "run_id":   job.get("run_id"),
    }
