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


# ─── Chart data for TradingView Lightweight Charts ───────────────────────────

def _build_chart_data(
    m15_df,
    setup: dict,
    candidates_raw: list[SetupCandidate],
    context_bars: int = 120,
) -> dict:
    """Build chart data dict for TradingView Lightweight Charts JS library."""
    cand = next((c for c in candidates_raw if c.bar_idx == setup["bar_idx"]), None)
    if cand is None:
        return {}

    bos_bar = cand.bos["bar_idx"]
    i       = cand.bar_idx
    start   = max(0, bos_bar - context_bars)
    end     = min(len(m15_df), i + 30)
    window  = m15_df.iloc[start:end].copy()

    if len(window) < 3:
        return {}

    fib = cand.fib
    bos = cand.bos

    # Candles — lightweight-charts uses Unix seconds
    candles = []
    for ts, row in window.iterrows():
        candles.append({
            "time":  int(ts.timestamp()),
            "open":  round(float(row["open"]),  5),
            "high":  round(float(row["high"]),  5),
            "low":   round(float(row["low"]),   5),
            "close": round(float(row["close"]), 5),
        })

    # Markers (BOS bar, NOW bar, sweeps)
    markers = []
    ts_map  = {c["time"]: idx for idx, c in enumerate(candles)}

    bos_offset  = bos_bar - start
    scan_offset = i - start

    if 0 <= bos_offset < len(candles):
        markers.append({
            "time":     candles[bos_offset]["time"],
            "position": "aboveBar",
            "color":    "#29b6f6",
            "shape":    "arrowDown",
            "text":     "BOS",
        })

    if 0 <= scan_offset < len(candles):
        markers.append({
            "time":     candles[scan_offset]["time"],
            "position": "aboveBar",
            "color":    "#00bcd4",
            "shape":    "circle",
            "text":     "NOW",
        })

    for sw in cand.sweeps:
        if sw.get("direction") == cand.direction:
            sw_ts = sw.get("timestamp")
            if sw_ts:
                try:
                    sw_unix = int(pd.Timestamp(sw_ts).timestamp())
                    if sw_unix in ts_map:
                        markers.append({
                            "time":     sw_unix,
                            "position": "belowBar",
                            "color":    "#e040fb",
                            "shape":    "arrowUp",
                            "text":     "SWEEP",
                        })
                except Exception:
                    pass

    # FVG zones
    fvgs = []
    for fvg in cand.fvgs:
        if fvg.get("mitigated") or fvg.get("direction") != cand.direction:
            continue
        fvgs.append({"top": round(float(fvg["top"]), 5),
                     "bottom": round(float(fvg["bottom"]), 5)})

    return {
        "candles":   candles,
        "markers":   sorted(markers, key=lambda m: m["time"]),
        "fvgs":      fvgs,
        "fib": {
            "sl":    round(float(fib.sl),    5),
            "entry": round(float(fib.entry), 5),
            "tp":    round(float(fib.tp),    5),
            "impulse_high": round(float(fib.impulse_high), 5),
            "impulse_low":  round(float(fib.impulse_low),  5),
        },
        "bos_level": round(float(bos["level"]), 5),
        "direction": cand.direction,
    }


# ─── HTML template (TradingView Lightweight Charts) ───────────────────────────

_HTML = """
<!DOCTYPE html>
<html lang="he">
<head>
<meta charset="utf-8">
<title>SMC Scanner — {{ setup.symbol }} #{{ setup.rank }}/{{ total }}</title>
<script src="https://cdn.jsdelivr.net/npm/lightweight-charts@4.2.0/dist/lightweight-charts.standalone.production.js"></script>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { background: #131722; color: #d1d4dc;
         font-family: -apple-system, 'Trebuchet MS', Arial, sans-serif;
         display: flex; flex-direction: column; height: 100vh; overflow: hidden; }

  /* ─ Top bar ─ */
  #topbar {
    background: #1e222d; border-bottom: 1px solid #2a2e39;
    padding: 8px 16px; display: flex; align-items: center;
    gap: 16px; flex-shrink: 0; height: 44px;
  }
  #topbar .progress { font-size: 20px; font-weight: 700; color: #fff; min-width: 80px; }
  #topbar .sym      { font-size: 14px; font-weight: 600; color: #d1d4dc; }
  #topbar .ts       { font-size: 12px; color: #787b86; }
  #topbar .badges   { display: flex; gap: 6px; margin-left: auto; }
  .badge { padding: 2px 10px; border-radius: 4px; font-size: 12px; font-weight: 700; }
  .badge-bull { background: #1a4731; color: #4caf50; border: 1px solid #2e7d32; }
  .badge-bear { background: #4d1d1d; color: #f44336; border: 1px solid #c62828; }
  .badge-fvg  { background: #332900; color: #ffd600; border: 1px solid #f57f17; }
  .badge-all  { background: #0a2744; color: '#29b6f6'; border: 1px solid #0277bd; }
  .badge-rr   { background: #1e222d; color: #d1d4dc; border: 1px solid #2a2e39; }

  /* ─ Chart area ─ */
  #chart-wrap { flex: 1; min-height: 0; position: relative; }
  #chart      { width: 100%; height: 100%; }

  /* ─ Bottom bar ─ */
  #bottombar {
    background: #1e222d; border-top: 1px solid #2a2e39;
    padding: 10px 16px; display: flex; align-items: center;
    gap: 12px; flex-shrink: 0; height: 60px;
  }
  .levels {
    display: flex; gap: 16px; font-size: 12px;
  }
  .level-item { display: flex; gap: 5px; align-items: center; }
  .level-dot  { width: 8px; height: 8px; border-radius: 50%; }
  .level-label{ color: #787b86; }
  .level-val  { font-weight: 700; font-variant-numeric: tabular-nums; }

  .btn {
    padding: 9px 28px; border: none; border-radius: 6px;
    font-size: 15px; font-weight: 700; cursor: pointer;
    transition: opacity 0.15s; outline: none;
  }
  .btn:hover  { opacity: 0.85; }
  .btn:active { opacity: 0.7; transform: scale(0.97); }
  #btn-yes { background: #2e7d32; color: #fff; }
  #btn-no  { background: #2a2e39; color: #d1d4dc; }
  #btn-quit{ background: transparent; color: #787b86; font-size: 12px;
             padding: 6px 14px; border: 1px solid #2a2e39; border-radius: 4px;
             margin-left: auto; }
  .shortcut { font-size: 10px; color: #4a4e5a; text-align: center; margin-top: 2px; }

  /* ─ Overlay (loading) ─ */
  #overlay {
    display: none; position: fixed; inset: 0;
    background: rgba(19,23,34,0.85); z-index: 100;
    align-items: center; justify-content: center;
    font-size: 18px; color: #d1d4dc;
  }
  #overlay.show { display: flex; }

  /* ─ Done screen ─ */
  #done-screen {
    display: none; position: fixed; inset: 0;
    background: #131722; z-index: 200;
    align-items: center; justify-content: center;
    flex-direction: column; gap: 14px;
  }
  #done-screen.show { display: flex; }
  #done-screen h1  { font-size: 26px; color: #4caf50; }
  #done-screen .summary { font-size: 15px; color: #787b86;
                          text-align: center; line-height: 2; }
</style>
</head>
<body>

<div id="overlay"><span>טוען…</span></div>
<div id="done-screen">
  <h1>✅ הסקאן הסתיים!</h1>
  <div class="summary" id="done-summary"></div>
  <p style="color:#4a4e5a;font-size:12px">הנתונים נשמרו. אפשר לסגור.</p>
</div>

<!-- Top bar -->
<div id="topbar">
  <div class="progress">{{ setup.rank }} / {{ total }}</div>
  <div class="sym">{{ symbol }}</div>
  <div class="ts">{{ setup.bos_timestamp[:16] }}</div>
  <div class="badges">
    <span class="badge {{ 'badge-bull' if setup.direction == 'bull' else 'badge-bear' }}">
      {{ '▲ LONG' if setup.direction == 'bull' else '▼ SHORT' }}
    </span>
    {% if setup.has_fvg %}<span class="badge badge-fvg">FVG</span>{% endif %}
    {% if setup.all_conditions_met %}<span class="badge badge-all" style="color:#29b6f6;">✓ כל התנאים</span>{% endif %}
    <span class="badge badge-rr">R:R {{ setup.rr }}:1</span>
  </div>
</div>

<!-- Chart -->
<div id="chart-wrap"><div id="chart"></div></div>

<!-- Bottom bar -->
<div id="bottombar">
  <div class="levels">
    <div class="level-item">
      <div class="level-dot" style="background:#f44336"></div>
      <span class="level-label">SL</span>
      <span class="level-val" style="color:#f44336">{{ setup.fib_sl }}</span>
    </div>
    <div class="level-item">
      <div class="level-dot" style="background:#ffd600"></div>
      <span class="level-label">Entry</span>
      <span class="level-val" style="color:#ffd600">{{ setup.fib_entry }}</span>
    </div>
    <div class="level-item">
      <div class="level-dot" style="background:#4caf50"></div>
      <span class="level-label">TP</span>
      <span class="level-val" style="color:#4caf50">{{ setup.fib_tp }}</span>
    </div>
  </div>

  <div style="display:flex;flex-direction:column;align-items:center;margin-left:12px">
    <button id="btn-yes" class="btn" onclick="decide('y')">✅ YES — לוקח</button>
    <div class="shortcut">Y</div>
  </div>
  <div style="display:flex;flex-direction:column;align-items:center">
    <button id="btn-no"  class="btn" onclick="decide('n')">❌ NO — מדלג</button>
    <div class="shortcut">N</div>
  </div>
  <button id="btn-quit" class="btn" onclick="decide('q')">יציאה</button>
</div>

<script>
const SETUP      = {{ setup_json | safe }};
const CHART_DATA = {{ chart_data | safe }};
const SETUP_IDX  = {{ setup.rank }};
const TOTAL      = {{ total }};
const LW         = LightweightCharts;

// ── Create chart ──────────────────────────────────────────────────────────────
const wrap = document.getElementById('chart-wrap');

// Calculate chart height explicitly — flex:1 height is 0 at script run time
function calcChartH() {
  const tb = document.getElementById('topbar').offsetHeight    || 44;
  const bb = document.getElementById('bottombar').offsetHeight || 60;
  return Math.max(200, window.innerHeight - tb - bb);
}
wrap.style.height = calcChartH() + 'px';

const chart = LW.createChart(wrap, {
  width:  wrap.clientWidth  || window.innerWidth,
  height: calcChartH(),
  layout: {
    background: { type: LW.ColorType.Solid, color: '#131722' },
    textColor: '#d1d4dc',
    fontSize: 12,
  },
  grid: {
    vertLines: { color: '#1e222d' },
    horzLines: { color: '#1e222d' },
  },
  crosshair: { mode: LW.CrosshairMode.Normal },
  rightPriceScale: {
    borderColor: '#2a2e39',
    scaleMargins: { top: 0.08, bottom: 0.08 },
  },
  timeScale: {
    borderColor: '#2a2e39',
    timeVisible: true,
    secondsVisible: false,
    fixLeftEdge: true,
    fixRightEdge: true,
  },
  handleScroll: true,
  handleScale:  true,
});

// ── Candlestick series ────────────────────────────────────────────────────────
const series = chart.addCandlestickSeries({
  upColor:        '#26a69a',
  downColor:      '#ef5350',
  borderUpColor:  '#26a69a',
  borderDownColor:'#ef5350',
  wickUpColor:    '#26a69a',
  wickDownColor:  '#ef5350',
});
series.setData(CHART_DATA.candles);

// ── Price lines (labels always visible on the right) ─────────────────────────
const fib = CHART_DATA.fib;

series.createPriceLine({
  price: fib.sl,    color: '#f44336', lineWidth: 1,
  lineStyle: LW.LineStyle.Dashed, axisLabelVisible: true, title: 'SL 100%',
});
series.createPriceLine({
  price: fib.entry, color: '#ffd600', lineWidth: 1,
  lineStyle: LW.LineStyle.Dashed, axisLabelVisible: true, title: 'Entry 75%',
});
series.createPriceLine({
  price: fib.tp,    color: '#4caf50', lineWidth: 1,
  lineStyle: LW.LineStyle.Dashed, axisLabelVisible: true, title: 'TP 0%',
});
series.createPriceLine({
  price: CHART_DATA.bos_level, color: '#29b6f6', lineWidth: 1,
  lineStyle: LW.LineStyle.Solid, axisLabelVisible: true, title: 'BOS',
});

// ── Markers ───────────────────────────────────────────────────────────────────
if (CHART_DATA.markers && CHART_DATA.markers.length)
  series.setMarkers(CHART_DATA.markers);

// ── Canvas overlay: Fib zone + FVG rectangles ─────────────────────────────────
function drawOverlays() {
  // Remove old overlay if any
  const old = wrap.querySelector('canvas.overlay');
  if (old) old.remove();

  const canvas = document.createElement('canvas');
  canvas.className = 'overlay';
  canvas.width  = wrap.clientWidth;
  canvas.height = wrap.clientHeight;
  canvas.style.cssText = 'position:absolute;top:0;left:0;pointer-events:none;';
  wrap.appendChild(canvas);

  const ctx = canvas.getContext('2d');

  // Fibonacci retracement zone (full impulse move)
  const dir    = CHART_DATA.direction;
  const fibTop = dir === 'bear' ? fib.sl : fib.tp;
  const fibBot = dir === 'bear' ? fib.tp : fib.sl;
  const yTop   = series.priceToCoordinate(fibTop);
  const yBot   = series.priceToCoordinate(fibBot);

  if (yTop !== null && yBot !== null && yBot > yTop) {
    const h = yBot - yTop;
    // Gradient fill: tight at entry level, fading outwards
    const grad = ctx.createLinearGradient(0, yTop, 0, yBot);
    grad.addColorStop(0, 'rgba(41,182,246,0.03)');
    grad.addColorStop(0.5,'rgba(41,182,246,0.09)');
    grad.addColorStop(1, 'rgba(41,182,246,0.03)');
    ctx.fillStyle = grad;
    ctx.fillRect(0, yTop, canvas.width, h);

    // Left edge label: "Fib zone"
    ctx.font = 'bold 10px Arial';
    ctx.fillStyle = 'rgba(41,182,246,0.55)';
    ctx.fillText('Fib zone', 6, yTop + 13);

    // Top & bottom anchor lines (thin)
    ctx.strokeStyle = 'rgba(41,182,246,0.25)';
    ctx.lineWidth = 1;
    ctx.setLineDash([4,4]);
    ctx.beginPath(); ctx.moveTo(0, yTop); ctx.lineTo(canvas.width, yTop); ctx.stroke();
    ctx.beginPath(); ctx.moveTo(0, yBot); ctx.lineTo(canvas.width, yBot); ctx.stroke();
    ctx.setLineDash([]);
  }

  // FVG zones (yellow)
  for (const fvg of (CHART_DATA.fvgs || [])) {
    const yF1 = series.priceToCoordinate(fvg.top);
    const yF2 = series.priceToCoordinate(fvg.bottom);
    if (yF1 !== null && yF2 !== null && yF2 > yF1) {
      ctx.fillStyle = 'rgba(255,235,59,0.10)';
      ctx.strokeStyle = 'rgba(255,235,59,0.3)';
      ctx.lineWidth = 0.5;
      ctx.fillRect(0, yF1, canvas.width, yF2 - yF1);
      ctx.strokeRect(0, yF1, canvas.width, yF2 - yF1);
      ctx.font = '9px Arial';
      ctx.fillStyle = 'rgba(255,235,59,0.55)';
      ctx.fillText('FVG', 6, yF1 + 11);
    }
  }
}

// Draw after chart has settled
setTimeout(drawOverlays, 250);

// Redraw overlays on scroll/zoom
chart.timeScale().subscribeVisibleLogicalRangeChange(() => {
  setTimeout(drawOverlays, 50);
});

// Responsive resize
window.addEventListener('resize', () => {
  const h = calcChartH();
  wrap.style.height = h + 'px';
  chart.applyOptions({ width: wrap.clientWidth, height: h });
  setTimeout(drawOverlays, 100);
});

// ── Keyboard shortcuts ────────────────────────────────────────────────────────
document.addEventListener('keydown', e => {
  if (e.key === 'y' || e.key === 'Y') decide('y');
  if (e.key === 'n' || e.key === 'N') decide('n');
  if (e.key === 'q' || e.key === 'Q') decide('q');
});

// ── Decision fetch ────────────────────────────────────────────────────────────
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
        `נסקרו: <strong>${data.reviewed}</strong><br>` +
        `נלקחו: <strong>${data.taken}</strong><br>` +
        `נשמר: <strong>${data.output_path}</strong>`;
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

    chart_data = _build_chart_data(
        STATE["m15_df"],
        setup,
        STATE["candidates_raw"],
    )

    return render_template_string(
        _HTML,
        setup=setup,
        total=len(setups),
        symbol=STATE["symbol"],
        chart_data=json.dumps(chart_data, cls=_Encoder),
        setup_json=json.dumps(setup, cls=_Encoder),
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
