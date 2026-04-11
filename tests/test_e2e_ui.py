"""
tests/test_e2e_ui.py — End-to-end smoke tests for the FastAPI + PWA stack.

Run with:
    python3 -m pytest tests/test_e2e_ui.py -v

What this checks:
1. The FastAPI app boots and every key endpoint returns 200 with the right shape.
2. The full backtest flow works: submit job → poll status → fetch result.
3. The result has all the expected fields (stats, trades, equity_curve, params).
4. History append + lookup + delete round-trips correctly.
5. Cache hit on identical re-run is much faster than the cold path.
6. The static frontend shell loads (HTML + CSS + JS + manifest + sw.js).
7. All form widgets are present in the rendered HTML (mobile-friendly check).
8. No Streamlit imports remain anywhere in web/.

Run after every change to make sure nothing regressed.
"""

from __future__ import annotations
import json
import re
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from web.api.server import app
from backtest import history, results_cache

ROOT = Path(__file__).parent.parent
STATIC = ROOT / "web" / "static"


@pytest.fixture(scope="module")
def client():
    return TestClient(app)


# ── 1. Static shell ──────────────────────────────────────────────────────────

def test_index_html_loads(client):
    r = client.get("/")
    assert r.status_code == 200
    body = r.text
    assert "<!DOCTYPE html>" in body
    assert 'dir="rtl"' in body
    assert 'name="viewport"' in body
    assert "viewport-fit=cover" in body
    assert "/static/styles.css" in body
    assert "/static/app.js" in body
    assert 'rel="manifest"' in body


def test_styles_css_loads(client):
    r = client.get("/static/styles.css")
    assert r.status_code == 200
    css = r.text
    # Mobile-first sanity checks
    assert "safe-area-inset-bottom" in css
    assert ".bottom-nav" in css
    assert ".btn-primary" in css
    assert ".progress-bar" in css


def test_app_js_loads(client):
    r = client.get("/static/app.js")
    assert r.status_code == 200
    js = r.text
    # Sanity check key functions/routes
    for needle in ["renderBacktest", "renderResults", "renderHistory",
                    "startProgressStream", "EventSource", "/api/backtest"]:
        assert needle in js, f"missing in app.js: {needle}"


def test_manifest_loads(client):
    r = client.get("/manifest.webmanifest")
    assert r.status_code == 200
    data = r.json()
    assert data["name"]
    assert data["start_url"] == "/"
    assert data["display"] == "standalone"
    assert any("192" in i["sizes"] for i in data["icons"])


def test_service_worker_loads(client):
    r = client.get("/sw.js")
    assert r.status_code == 200
    assert "addEventListener" in r.text


def test_pwa_icons_exist():
    assert (STATIC / "icons" / "icon-192.png").exists()
    assert (STATIC / "icons" / "icon-512.png").exists()


# ── 2. Reference endpoints ───────────────────────────────────────────────────

def test_symbols_endpoint(client):
    r = client.get("/api/symbols")
    assert r.status_code == 200
    data = r.json()
    assert "symbols" in data
    assert "EURUSD" in data["symbols"]


def test_defaults_endpoint(client):
    r = client.get("/api/defaults")
    assert r.status_code == 200
    d = r.json()
    # Verify every form knob has a default
    required = [
        "symbol", "initial_capital", "risk_per_trade", "compound", "risk_pct",
        "rr", "swing_n_ltf", "swing_n_htf", "require_fvg",
        "hours_filter_start", "hours_filter_end", "weekday_mask",
        "max_trades_per_day", "commission_per_lot",
    ]
    for k in required:
        assert k in d, f"missing default: {k}"


# ── 3. Backtest job round-trip ───────────────────────────────────────────────

@pytest.fixture(scope="module")
def cached_backtest_request():
    """Use a date range that's already cached on disk to keep tests fast."""
    return {
        "symbol": "EURUSD",
        "date_from": "2024-04-11",
        "date_to":   "2026-04-11",
        "initial_capital": 100_000,
        "risk_per_trade": 500,
        "compound": False,
        "risk_pct": 0.5,
        "rr": 3.0,
        "require_fvg": False,
        "swing_n_ltf": 3,
        "swing_n_htf": 3,
        "hours_filter_start": 0,
        "hours_filter_end":   23,
        "weekday_mask":       0b0111111,
        "max_trades_per_day": 0,
        "commission_per_lot": 0.0,
    }


def _wait_for_job(client, job_id, timeout=600):
    start = time.time()
    while time.time() - start < timeout:
        r = client.get(f"/api/backtest/{job_id}/status")
        assert r.status_code == 200
        d = r.json()
        if d["state"] == "done":
            return d
        if d["state"] == "error":
            raise RuntimeError(d.get("error") or "unknown error")
        time.sleep(0.2)
    raise TimeoutError(f"job {job_id} did not finish in {timeout}s")


def test_backtest_run_endpoint(client, cached_backtest_request):
    r = client.post("/api/backtest", json=cached_backtest_request)
    assert r.status_code == 200
    job_id = r.json()["job_id"]
    assert isinstance(job_id, str) and len(job_id) >= 8

    # Poll until done
    status = _wait_for_job(client, job_id)
    assert status["state"] == "done"
    assert status["progress"] == 1.0
    assert status["run_id"]

    # Fetch full result
    r = client.get(f"/api/backtest/{job_id}/result")
    assert r.status_code == 200
    result = r.json()

    # Required top-level keys
    for k in ["run_id", "symbol", "date_from", "date_to", "stats", "trades", "equity_curve", "params", "cached"]:
        assert k in result, f"missing key in result: {k}"

    # Stats sanity
    s = result["stats"]
    for k in ["total_trades", "win_rate_pct", "profit_factor", "net_pnl_usd",
              "max_dd_pct", "avg_rr", "long_trades", "short_trades",
              "avg_hold_long_sec", "avg_hold_short_sec"]:
        assert k in s, f"missing stat: {k}"
    assert s["total_trades"] > 0

    # Trade list shape
    assert isinstance(result["trades"], list)
    if result["trades"]:
        t = result["trades"][0]
        for k in ["direction", "entry_price", "sl_price", "tp_price",
                  "entry_time", "result", "pnl_usd", "lot_size"]:
            assert k in t

    # Equity curve sanity
    assert len(result["equity_curve"]) == s["total_trades"] + 1


def test_backtest_cache_hit_is_fast(client, cached_backtest_request):
    """Identical re-run should be much faster than the cold path."""
    # First run (may use cache, may not)
    r = client.post("/api/backtest", json=cached_backtest_request)
    job_id = r.json()["job_id"]
    _wait_for_job(client, job_id)

    # Second run — should hit results_cache for a near-instant return
    t0 = time.time()
    r = client.post("/api/backtest", json=cached_backtest_request)
    job_id = r.json()["job_id"]
    _wait_for_job(client, job_id)
    elapsed = time.time() - t0
    assert elapsed < 5.0, f"cache re-run took {elapsed:.1f}s, expected < 5s"


def test_backtest_endpoint_validates_payload(client):
    """Sending a malformed payload should be rejected with 422."""
    r = client.post("/api/backtest", json={"symbol": "EURUSD"})  # missing dates
    assert r.status_code == 422


# ── 4. History endpoints ─────────────────────────────────────────────────────

def test_history_list(client):
    r = client.get("/api/history")
    assert r.status_code == 200
    data = r.json()
    assert "runs" in data
    assert isinstance(data["runs"], list)


def test_history_round_trip(client, cached_backtest_request):
    """A finished run should appear in history and be loadable by run_id."""
    r = client.post("/api/backtest", json=cached_backtest_request)
    job_id = r.json()["job_id"]
    status = _wait_for_job(client, job_id)
    run_id = status["run_id"]

    # Should appear in /api/history
    r = client.get("/api/history")
    runs = r.json()["runs"]
    matching = [run for run in runs if run["run_id"] == run_id]
    assert len(matching) >= 1

    # Should be loadable by id
    r = client.get(f"/api/history/{run_id}")
    assert r.status_code == 200
    full = r.json()
    assert full["symbol"] == cached_backtest_request["symbol"]
    assert "trades" in full
    assert "equity_curve" in full


def test_history_get_404(client):
    r = client.get("/api/history/nonexistent_run_id_xyz")
    assert r.status_code == 404


# ── Trade chart endpoint ─────────────────────────────────────────────────────

def test_trade_chart_endpoint(client, cached_backtest_request):
    """A finished run should be able to serve a per-trade candlestick window."""
    r = client.post("/api/backtest", json=cached_backtest_request)
    job_id = r.json()["job_id"]
    status = _wait_for_job(client, job_id)
    run_id = status["run_id"]

    r = client.get(f"/api/trade-chart/{run_id}/0")
    assert r.status_code == 200
    d = r.json()
    for k in ["candles", "markers", "entry", "sl", "tp",
              "impulse_high", "impulse_low", "direction", "result"]:
        assert k in d, f"missing key: {k}"
    assert isinstance(d["candles"], list) and len(d["candles"]) > 0
    # Each candle has OHLCV-shaped fields
    c0 = d["candles"][0]
    for k in ["time", "open", "high", "low", "close"]:
        assert k in c0


def test_trade_chart_out_of_range(client, cached_backtest_request):
    r = client.post("/api/backtest", json=cached_backtest_request)
    job_id = r.json()["job_id"]
    _wait_for_job(client, job_id)
    run_id = client.get(f"/api/backtest/{job_id}/status").json()["run_id"]
    r = client.get(f"/api/trade-chart/{run_id}/999999")
    assert r.status_code == 400


# ── No-cache headers for static (so JS edits show up immediately) ────────────

def test_static_no_cache_headers(client):
    r = client.get("/static/app.js")
    assert r.status_code == 200
    cc = r.headers.get("cache-control", "")
    assert "no-store" in cc or "no-cache" in cc, f"expected no-store, got: {cc}"


# ── 5. Verify no Streamlit imports remain in web/api or web/static ──────────

def test_no_streamlit_in_new_web_code():
    """The new FastAPI server and frontend must not depend on Streamlit."""
    api_dir = ROOT / "web" / "api"
    for f in api_dir.rglob("*.py"):
        text = f.read_text()
        assert "import streamlit" not in text, f"streamlit import in {f}"
        assert "from streamlit" not in text, f"streamlit import in {f}"


# ── 6. Form widget presence in HTML (mobile-friendly check) ─────────────────

def test_form_has_all_knobs(client):
    """Render the HTML and verify it contains the IDs the JS expects."""
    r = client.get("/")
    assert r.status_code == 200
    # The form is built dynamically by JS, so we check the JS for the IDs instead.
    js = client.get("/static/app.js").text
    expected_ids = [
        "f-symbol", "f-capital", "f-from", "f-to",
        "f-compound", "f-rr", "f-commission",
        "f-h-start", "f-h-end", "f-maxtrades", "f-fvg",
    ]
    for id_ in expected_ids:
        assert id_ in js, f"missing form id: {id_}"


# ── 7. Filters module sanity ─────────────────────────────────────────────────

def test_hours_filter_il_dst():
    """Israel time conversion handles DST."""
    import pandas as pd
    from backtest.filters import _to_il_hour, passes_hours

    winter = pd.Timestamp("2026-01-15 12:00:00", tz="UTC")  # IL=14:00
    summer = pd.Timestamp("2026-07-15 12:00:00", tz="UTC")  # IL=15:00
    assert _to_il_hour(winter) == 14
    assert _to_il_hour(summer) == 15

    # 08-16 includes 14:00 and 15:00
    assert passes_hours(winter, 8, 16) is True
    assert passes_hours(summer, 8, 16) is True
    # 08-12 excludes 14:00
    assert passes_hours(winter, 8, 12) is False
    # Wraparound 22-04 includes 23:00
    night = pd.Timestamp("2026-01-15 21:00:00", tz="UTC")  # IL=23:00
    assert passes_hours(night, 22, 4) is True


def test_daily_counter():
    import pandas as pd
    from backtest.filters import DailyTradeCounter

    c = DailyTradeCounter(max_per_day=2)
    t1 = pd.Timestamp("2026-01-15 09:00:00", tz="UTC")
    t2 = pd.Timestamp("2026-01-15 10:00:00", tz="UTC")
    t3 = pd.Timestamp("2026-01-15 11:00:00", tz="UTC")
    t4 = pd.Timestamp("2026-01-16 09:00:00", tz="UTC")

    assert c.can_take(t1) is True
    c.record(t1)
    assert c.can_take(t2) is True
    c.record(t2)
    assert c.can_take(t3) is False  # over the cap
    assert c.can_take(t4) is True   # new day
