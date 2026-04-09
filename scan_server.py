"""
scan_server.py — Local web server for visual SMC setup review.

Scans M15+H1 data for BOS+Sweep setups, then serves an interactive
candlestick chart with YES/NO buttons in the browser.

Usage:
    python3 scan_server.py --symbol EURUSD --from 2024-01-01 --to 2024-04-01

Options:
    --symbol   : MT5 symbol (e.g. EURUSD)
    --from     : start date YYYY-MM-DD
    --to       : end date YYYY-MM-DD
    --source   : auto | yfinance | oanda | bridge (default: auto)
    --max      : max setups to review (default: 25, best-scored first)
    --port     : server port (default: 5001)
    --no-cache : ignore saved scan cache and re-scan

Keyboard shortcuts in browser:
    Y  — take trade
    N  — skip
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import threading
import time
import webbrowser
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

# ── Path setup ───────────────────────────────────────────────────────────────
ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))


class _Encoder(json.JSONEncoder):
    """Convert pandas/numpy types that json can't handle."""
    def default(self, obj):
        if isinstance(obj, pd.Timestamp):
            return str(obj)
        if isinstance(obj, np.integer):
            return int(obj)
        if isinstance(obj, np.floating):
            return float(obj)
        if isinstance(obj, np.bool_):
            return bool(obj)
        return super().default(obj)

import config
from data.fetcher import get_ohlcv, _detect_source


def _load_duka_csv(path, date_from: str, date_to: str) -> pd.DataFrame:
    """Load a Dukascopy CSV produced by download_data.py, filtered to date range."""
    df = pd.read_csv(path, parse_dates=["time"], index_col="time")
    df.index = pd.to_datetime(df.index, utc=True)
    df = df.sort_index()
    return df[date_from:date_to]
from review.scanner import scan_setups, SetupCandidate

from flask import Flask, jsonify, redirect, render_template_string, request, url_for
import plotly.graph_objects as go

# ── Flask app ─────────────────────────────────────────────────────────────────
app = Flask(__name__)
app.config["TEMPLATES_AUTO_RELOAD"] = True

# ── Global state (loaded once at startup) ────────────────────────────────────
STATE: dict = {
    "setups":      [],   # list of dicts (serialisable SetupCandidate)
    "decisions":   {},   # {index: "y"|"n"}
    "symbol":      "",
    "output_path": "",
    "done":        False,
}


# ─── Scoring / ranking ────────────────────────────────────────────────────────

def _score(cand: SetupCandidate) -> float:
    """
    Rank setups without changing strategy rules.
    Higher = better quality setup.

    Points:
      +3  FVG present near entry
      +2  All 5 conditions met (price in entry zone)
      +1  R:R >= 3
      +1  R:R >= 4
      -1  very small swing (impulse < half the avg range) → noisy
    """
    fib = cand.fib
    score = 0.0

    if cand.has_fvg_near_entry:
        score += 3
    if cand.all_conditions_met:
        score += 2

    rr = fib.tp_distance / fib.sl_distance if fib.sl_distance > 0 else 0
    if rr >= 3:
        score += 1
    if rr >= 4:
        score += 1

    return score


def _top_setups(candidates: list[SetupCandidate], max_n: int) -> list[SetupCandidate]:
    """Return up to max_n setups, best-scored first, then chronological."""
    scored = sorted(candidates, key=lambda c: (-_score(c), c.bar_idx))
    return scored[:max_n]


# ─── Serialise candidate → dict for JSON / template ─────────────────────────

def _serialise(cand: SetupCandidate, rank: int) -> dict:
    fib = cand.fib
    bos = cand.bos
    rr  = fib.tp_distance / fib.sl_distance if fib.sl_distance > 0 else 0
    return {
        "rank":               rank,
        "bar_idx":            cand.bar_idx,
        "bar_time":           str(cand.bar_time),
        "direction":          cand.direction,
        "bos_level":          round(bos["level"], 5),
        "bos_timestamp":      str(bos["timestamp"]),
        "fib_entry":          round(fib.entry, 5),
        "fib_sl":             round(fib.sl, 5),
        "fib_tp":             round(fib.tp, 5),
        "rr":                 round(rr, 2),
        "score":              _score(cand),
        "has_fvg":            cand.has_fvg_near_entry,
        "all_conditions_met": cand.all_conditions_met,
        "sweeps":             cand.sweeps,
        "fvgs":               cand.fvgs,
    }


# ─── Plotly chart JSON ───────────────────────────────────────────────────────

def _build_chart_json(
    m15_df,
    setup: dict,
    candidates_raw: list[SetupCandidate],
    context_bars: int = 120,
) -> str:
    """Build Plotly figure JSON for a single setup."""
    # Find the raw candidate matching this setup
    cand = next((c for c in candidates_raw if c.bar_idx == setup["bar_idx"]), None)
    if cand is None:
        return "{}"

    bos_bar = cand.bos["bar_idx"]
    i       = cand.bar_idx
    start   = max(0, bos_bar - context_bars)
    end     = min(len(m15_df), i + 30)
    window  = m15_df.iloc[start:end].copy()

    if len(window) < 3:
        return "{}"

    ts = window.index.astype(str).tolist()
    fib = cand.fib
    bos = cand.bos

    candle = go.Candlestick(
        x=ts,
        open=window["open"], high=window["high"],
        low=window["low"],   close=window["close"],
        name="Price",
        increasing_line_color="#26a69a",
        decreasing_line_color="#ef5350",
        increasing_fillcolor="#26a69a",
        decreasing_fillcolor="#ef5350",
    )

    shapes      = []
    annotations = []

    def hline(price, color, dash="dash", width=1.5):
        shapes.append(dict(
            type="line", xref="x", yref="y",
            x0=ts[0], x1=ts[-1],
            y0=price, y1=price,
            line=dict(color=color, width=width, dash=dash),
        ))

    def label_right(price, text, color):
        annotations.append(dict(
            x=ts[-1], y=price, xref="x", yref="y",
            text=f"<b>{text}</b>", showarrow=False,
            xanchor="left", font=dict(color=color, size=11),
        ))

    hline(fib.tp,      "#00e676")
    hline(fib.entry,   "#ffd600")
    hline(fib.sl,      "#f44336")
    hline(bos["level"], "#29b6f6", dash="solid", width=1.2)

    label_right(fib.tp,       f"TP  {fib.tp:.5f}",       "#00e676")
    label_right(fib.entry,    f"Entry {fib.entry:.5f}",   "#ffd600")
    label_right(fib.sl,       f"SL  {fib.sl:.5f}",        "#f44336")
    label_right(bos["level"], f"BOS {bos['level']:.5f}",  "#29b6f6")

    # FVG zones
    for fvg in cand.fvgs:
        if fvg.get("mitigated") or fvg.get("direction") != cand.direction:
            continue
        fvg_ts = str(fvg.get("timestamp", ts[0]))
        x0 = fvg_ts if fvg_ts in ts else ts[0]
        shapes.append(dict(
            type="rect", xref="x", yref="y",
            x0=x0, x1=ts[-1],
            y0=fvg["bottom"], y1=fvg["top"],
            fillcolor="rgba(255,235,59,0.12)",
            line=dict(width=0),
        ))

    # BOS bar vertical
    bos_offset = bos_bar - start
    if 0 <= bos_offset < len(ts):
        shapes.append(dict(
            type="line", xref="x", yref="paper",
            x0=ts[bos_offset], x1=ts[bos_offset],
            y0=0, y1=1,
            line=dict(color="#29b6f6", width=1, dash="dot"),
        ))
        annotations.append(dict(
            x=ts[bos_offset], y=0.99, xref="x", yref="paper",
            text="BOS", showarrow=False, yanchor="top",
            font=dict(color="#29b6f6", size=10),
        ))

    # NOW bar vertical
    scan_offset = i - start
    if 0 <= scan_offset < len(ts):
        shapes.append(dict(
            type="line", xref="x", yref="paper",
            x0=ts[scan_offset], x1=ts[scan_offset],
            y0=0, y1=1,
            line=dict(color="#00bcd4", width=1.5, dash="dot"),
        ))
        annotations.append(dict(
            x=ts[scan_offset], y=0.99, xref="x", yref="paper",
            text="NOW", showarrow=False, yanchor="top",
            font=dict(color="#00bcd4", size=10),
        ))

    # Sweep markers
    sweep_x, sweep_y = [], []
    for sw in cand.sweeps:
        if sw.get("direction") == cand.direction:
            sw_ts = str(sw.get("timestamp", ""))
            if sw_ts in ts:
                idx2 = ts.index(sw_ts)
                sweep_x.append(sw_ts)
                sweep_y.append(window.iloc[idx2]["low"] * 0.9993)

    sweep_trace = go.Scatter(
        x=sweep_x, y=sweep_y,
        mode="markers",
        marker=dict(symbol="triangle-up", size=14, color="#e040fb"),
        name="Sweep", showlegend=False,
    )

    fig = go.Figure(data=[candle, sweep_trace])
    fig.update_layout(
        paper_bgcolor="#131722",
        plot_bgcolor="#131722",
        font=dict(color="#d1d4dc"),
        xaxis=dict(
            rangeslider=dict(visible=False),
            gridcolor="#1e2130",
            type="category",
            tickangle=-45,
            nticks=20,
        ),
        yaxis=dict(gridcolor="#1e2130"),
        shapes=shapes,
        annotations=annotations,
        margin=dict(l=60, r=130, t=20, b=60),
        height=520,
        showlegend=False,
    )

    return fig.to_json()


# ─── HTML template ────────────────────────────────────────────────────────────

_HTML = """
<!DOCTYPE html>
<html lang="he" dir="rtl">
<head>
<meta charset="utf-8">
<title>SMC Scanner — {{ setup.symbol }} #{{ setup.rank }}/{{ total }}</title>
<script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { background: #0d1117; color: #e6edf3; font-family: 'SF Pro', Arial, sans-serif;
         display: flex; flex-direction: column; height: 100vh; overflow: hidden; }

  /* ─ Top bar ─ */
  #topbar {
    background: #161b22; border-bottom: 1px solid #30363d;
    padding: 10px 20px; display: flex; align-items: center;
    gap: 20px; flex-shrink: 0;
  }
  #topbar .progress { font-size: 22px; font-weight: 700; color: #f0f6fc; }
  #topbar .meta    { font-size: 13px; color: #8b949e; }
  #topbar .badges  { display: flex; gap: 8px; margin-left: auto; }
  .badge { padding: 3px 10px; border-radius: 12px; font-size: 12px; font-weight: 600; }
  .badge-bull { background: #1a4731; color: #3fb950; }
  .badge-bear { background: #4d1d1d; color: #f85149; }
  .badge-fvg  { background: #2d2500; color: #ffd600; }
  .badge-all  { background: #0d3349; color: #29b6f6; }
  .badge-rr   { background: #1e1e2e; color: #c9d1d9; }

  /* ─ Chart ─ */
  #chart-wrap { flex: 1; min-height: 0; }
  #chart      { width: 100%; height: 100%; }

  /* ─ Bottom bar ─ */
  #bottombar {
    background: #161b22; border-top: 1px solid #30363d;
    padding: 12px 20px; display: flex; align-items: center;
    gap: 16px; flex-shrink: 0;
  }
  .info-block { font-size: 12px; color: #8b949e; line-height: 1.6; }
  .info-block span { color: #e6edf3; font-weight: 600; }

  .btn {
    padding: 10px 36px; border: none; border-radius: 8px; font-size: 16px;
    font-weight: 700; cursor: pointer; transition: filter 0.15s; outline: none;
  }
  .btn:hover { filter: brightness(1.2); }
  .btn:active { filter: brightness(0.85); transform: scale(0.97); }
  #btn-yes { background: #238636; color: #fff; }
  #btn-no  { background: #30363d; color: #e6edf3; }
  #btn-quit{ background: #21262d; color: #8b949e; margin-left: auto; font-size: 13px; padding: 8px 20px; }

  .shortcut { font-size: 11px; color: #6e7681; margin-top: 2px; }

  /* ─ Loading overlay ─ */
  #overlay {
    display: none; position: fixed; inset: 0;
    background: rgba(13,17,23,0.85); z-index: 100;
    align-items: center; justify-content: center; font-size: 20px; color: #e6edf3;
  }
  #overlay.show { display: flex; }

  /* ─ Done screen ─ */
  #done-screen {
    display: none; position: fixed; inset: 0;
    background: #0d1117; z-index: 200;
    align-items: center; justify-content: center; flex-direction: column; gap: 16px;
  }
  #done-screen.show { display: flex; }
  #done-screen h1  { font-size: 28px; color: #3fb950; }
  #done-screen .summary { font-size: 16px; color: #8b949e; text-align: center; line-height: 2; }
</style>
</head>
<body>

<!-- Loading overlay -->
<div id="overlay"><span>טוען…</span></div>

<!-- Done screen -->
<div id="done-screen">
  <h1>✅ הסקאן הסתיים!</h1>
  <div class="summary" id="done-summary"></div>
  <p style="color:#6e7681;font-size:13px">הנתונים נשמרו אוטומטית. אפשר לסגור את הדפדפן.</p>
</div>

<!-- Top bar -->
<div id="topbar">
  <div class="progress">#{{ setup.rank }} / {{ total }}</div>
  <div class="meta">{{ symbol }}  |  {{ setup.bos_timestamp[:16] }}</div>
  <div class="badges">
    <span class="badge {{ 'badge-bull' if setup.direction == 'bull' else 'badge-bear' }}">
      {{ '▲ BULL' if setup.direction == 'bull' else '▼ BEAR' }}
    </span>
    {% if setup.has_fvg %}<span class="badge badge-fvg">FVG ✓</span>{% endif %}
    {% if setup.all_conditions_met %}<span class="badge badge-all">כל התנאים ✓</span>{% endif %}
    <span class="badge badge-rr">R:R {{ setup.rr }}:1</span>
  </div>
</div>

<!-- Chart -->
<div id="chart-wrap"><div id="chart"></div></div>

<!-- Bottom bar -->
<div id="bottombar">
  <div class="info-block">
    Entry <span>{{ setup.fib_entry }}</span><br>
    SL &nbsp;&nbsp;&nbsp;<span>{{ setup.fib_sl }}</span><br>
    TP &nbsp;&nbsp;&nbsp;<span>{{ setup.fib_tp }}</span>
  </div>
  <div style="display:flex;flex-direction:column;align-items:center;gap:4px">
    <button id="btn-yes" class="btn" onclick="decide('y')">✅ YES — לוקח</button>
    <div class="shortcut">מקשור: Y</div>
  </div>
  <div style="display:flex;flex-direction:column;align-items:center;gap:4px">
    <button id="btn-no"  class="btn" onclick="decide('n')">❌ NO — מדלג</button>
    <div class="shortcut">מקשור: N</div>
  </div>
  <button id="btn-quit" class="btn" onclick="decide('q')">יציאה</button>
</div>

<script>
const CHART_JSON = {{ chart_json | safe }};
const SETUP_IDX  = {{ setup.rank }};
const TOTAL      = {{ total }};

// Render chart
Plotly.newPlot('chart', CHART_JSON.data, CHART_JSON.layout, {
  responsive: true, scrollZoom: true, displaylogo: false,
  modeBarButtonsToRemove: ['toImage','sendDataToCloud'],
});

// Keyboard shortcuts
document.addEventListener('keydown', e => {
  if (e.key === 'y' || e.key === 'Y') decide('y');
  if (e.key === 'n' || e.key === 'N') decide('n');
  if (e.key === 'q' || e.key === 'Q') decide('q');
});

function decide(ans) {
  document.getElementById('overlay').classList.add('show');
  fetch('/decide', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({rank: SETUP_IDX, answer: ans})
  })
  .then(r => r.json())
  .then(data => {
    if (data.done) {
      document.getElementById('overlay').classList.remove('show');
      document.getElementById('done-summary').innerHTML =
        `סה"כ נסקרו: <strong>${data.reviewed}</strong><br>` +
        `עסקאות שנלקחו: <strong>${data.taken}</strong><br>` +
        `נשמר ל: <strong>${data.output_path}</strong>`;
      document.getElementById('done-screen').classList.add('show');
    } else {
      window.location.href = '/setup/' + data.next_rank;
    }
  });
}
</script>
</body>
</html>
"""

# ─── Routes ──────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    # Find first undecided setup
    for s in STATE["setups"]:
        if s["rank"] not in STATE["decisions"]:
            return redirect(f"/setup/{s['rank']}")
    return redirect("/setup/1")


@app.route("/setup/<int:rank>")
def show_setup(rank):
    setups = STATE["setups"]
    if not setups:
        return "No setups found.", 404

    setup = next((s for s in setups if s["rank"] == rank), None)
    if setup is None:
        return redirect("/")

    setup["symbol"] = STATE["symbol"]

    # Build chart JSON
    chart_json = _build_chart_json(
        STATE["m15_df"],
        setup,
        STATE["candidates_raw"],
    )

    return render_template_string(
        _HTML,
        setup=setup,
        total=len(setups),
        symbol=STATE["symbol"],
        chart_json=chart_json,
    )


@app.route("/decide", methods=["POST"])
def decide():
    data   = request.get_json()
    rank   = data.get("rank")
    answer = data.get("answer")

    STATE["decisions"][rank] = answer

    # Save immediately after every decision
    _save_decisions()

    if answer == "q":
        STATE["done"] = True
        taken    = sum(1 for v in STATE["decisions"].values() if v == "y")
        reviewed = len(STATE["decisions"])
        return jsonify(done=True, reviewed=reviewed, taken=taken,
                       output_path=STATE["output_path"])

    # Find next undecided
    decided = set(STATE["decisions"].keys())
    remaining = [s for s in STATE["setups"] if s["rank"] not in decided]

    if not remaining:
        STATE["done"] = True
        taken    = sum(1 for v in STATE["decisions"].values() if v == "y")
        reviewed = len(STATE["decisions"])
        return jsonify(done=True, reviewed=reviewed, taken=taken,
                       output_path=STATE["output_path"])

    return jsonify(done=False, next_rank=remaining[0]["rank"])


def _save_decisions():
    """Save decisions JSON to disk."""
    setups    = STATE["setups"]
    decisions = STATE["decisions"]
    symbol    = STATE["symbol"]

    records = []
    for s in setups:
        d = STATE["decisions"].get(s["rank"])
        if d is None:
            continue
        records.append({
            "rank":               s["rank"],
            "symbol":             symbol,
            "direction":          s["direction"],
            "bar_time":           s["bar_time"],
            "bos_level":          s["bos_level"],
            "bos_timestamp":      s["bos_timestamp"],
            "fib_entry":          s["fib_entry"],
            "fib_sl":             s["fib_sl"],
            "fib_tp":             s["fib_tp"],
            "rr":                 s["rr"],
            "score":              s["score"],
            "has_fvg":            s["has_fvg"],
            "all_conditions_met": s["all_conditions_met"],
            "decision":           d,
        })

    with open(STATE["output_path"], "w") as f:
        json.dump(records, f, indent=2, cls=_Encoder)


# ─── Cache helpers ────────────────────────────────────────────────────────────

def _cache_key(symbol, date_from, date_to, source) -> str:
    raw = f"{symbol}_{date_from}_{date_to}_{source}"
    return hashlib.md5(raw.encode()).hexdigest()[:12]


def _cache_path(key: str) -> Path:
    d = ROOT / ".scan_cache"
    d.mkdir(exist_ok=True)
    return d / f"{key}.json"


def _save_cache(key, data):
    with open(_cache_path(key), "w") as f:
        json.dump(data, f, cls=_Encoder)


def _load_cache(key):
    p = _cache_path(key)
    if p.exists():
        try:
            with open(p) as f:
                return json.load(f)
        except (json.JSONDecodeError, Exception):
            p.unlink(missing_ok=True)   # delete corrupt cache
    return None


# ─── Main ────────────────────────────────────────────────────────────────────

def main():
    p = argparse.ArgumentParser(description="SMC Setup Scanner Web UI")
    p.add_argument("--symbol",   required=True,  help="Symbol e.g. EURUSD")
    p.add_argument("--from",     dest="date_from", required=True)
    p.add_argument("--to",       dest="date_to",   required=True)
    p.add_argument("--source",   default="auto",
                   choices=["auto","mt5","oanda","yfinance","bridge","dukascopy"])
    p.add_argument("--max",      type=int, default=25,
                   help="Max setups to review (default: 25, best-scored first)")
    p.add_argument("--port",     type=int, default=5001)
    p.add_argument("--no-cache", dest="no_cache", action="store_true",
                   help="Ignore saved scan cache and re-scan")
    args = p.parse_args()

    symbol = args.symbol.upper()
    source = args.source if args.source != "auto" else _detect_source()
    print(f"\n  SMC Scanner  |  {symbol}  {args.date_from} → {args.date_to}"
          f"  |  source: {source}\n")

    # ── Load data ─────────────────────────────────────────────────────────────
    print("  Loading market data…")

    if source == "dukascopy":
        # Auto-load from downloaded CSVs (run download_data.py first)
        cache_dir = ROOT / "data" / "cache"
        m15_csv = cache_dir / f"{symbol}_M15_dukascopy.csv"
        h1_csv  = cache_dir / f"{symbol}_H1_dukascopy.csv"

        if not m15_csv.exists() or not h1_csv.exists():
            missing = [str(f) for f in [m15_csv, h1_csv] if not f.exists()]
            print(f"\n  ERROR: Dukascopy CSV not found: {missing}")
            print(f"  Run first:\n  python3 download_data.py --symbol {symbol} "
                  f"--from {args.date_from} --to {args.date_to}\n")
            return

        m15_df = _load_duka_csv(m15_csv, args.date_from, args.date_to)
        h1_df  = _load_duka_csv(h1_csv,  args.date_from, args.date_to)
    else:
        m15_df = get_ohlcv(symbol, "M15", args.date_from, args.date_to, source=args.source)
        h1_df  = get_ohlcv(symbol, "H1",  args.date_from, args.date_to, source=args.source)

    print(f"  15M bars: {len(m15_df):,}  |  1H bars: {len(h1_df):,}")

    # ── Scan (with cache) ─────────────────────────────────────────────────────
    ckey      = _cache_key(symbol, args.date_from, args.date_to, source)
    cached    = None if args.no_cache else _load_cache(ckey)

    if cached is not None:
        print(f"  Loaded {len(cached)} setups from cache  (use --no-cache to re-scan)")
        # We still need raw candidates for chart building — re-scan silently
        # but use cached ranking/scoring
        candidates_raw = scan_setups(m15_df, h1_df, symbol)
    else:
        candidates_raw = scan_setups(m15_df, h1_df, symbol)

    if not candidates_raw:
        print("\n  No setups found. Try a longer date range or different symbol.")
        return

    # ── Rank & limit ──────────────────────────────────────────────────────────
    top = _top_setups(candidates_raw, args.max)
    print(f"  Showing top {len(top)} of {len(candidates_raw)} setups "
          f"(ranked by: FVG presence, all-conditions, R:R)\n")

    serialised = [_serialise(c, i + 1) for i, c in enumerate(top)]

    # ── Save cache ────────────────────────────────────────────────────────────
    _save_cache(ckey, serialised)

    # ── Output file ───────────────────────────────────────────────────────────
    ts          = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = str(ROOT / f"scan_decisions_{symbol}_{ts}.json")

    # ── Populate global state ─────────────────────────────────────────────────
    STATE["setups"]         = serialised
    STATE["candidates_raw"] = candidates_raw
    STATE["m15_df"]         = m15_df
    STATE["symbol"]         = symbol
    STATE["output_path"]    = output_path

    # ── Open browser after short delay ───────────────────────────────────────
    url = f"http://localhost:{args.port}"
    print(f"  Opening browser at {url}")
    print(f"  Press Ctrl+C in this terminal to stop the server.\n")

    def _open():
        time.sleep(1.2)
        webbrowser.open(url)

    threading.Thread(target=_open, daemon=True).start()

    # ── Start Flask ───────────────────────────────────────────────────────────
    app.run(host="127.0.0.1", port=args.port, debug=False, use_reloader=False)


if __name__ == "__main__":
    main()
