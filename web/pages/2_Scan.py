"""
web/pages/2_Scan.py — Manual setup scanner with TradingView Lightweight Charts.

Scans M15+H1 data for BOS+Sweep candidates, then displays each setup
with a TradingView chart (BOS, Fib levels, FVG zones).
User clicks YES/NO to record decisions.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import json
import streamlit as st
import streamlit.components.v1 as components
import pandas as pd
import numpy as np

st.set_page_config(page_title="Scan Mode", layout="wide", page_icon="🔍",
                   initial_sidebar_state="collapsed")

from web.mobile_css import inject_mobile_css
inject_mobile_css()

st.title("🔍 Scan Mode")

import config
from data.fetcher import get_ohlcv
from review.scanner import scan_setups, SetupCandidate
from strategy.fibonacci import calculate_fib_levels


class _Encoder(json.JSONEncoder):
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


def _score(cand: SetupCandidate) -> float:
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


def _build_chart_data(m15_df, cand: SetupCandidate, context_bars: int = 200) -> dict:
    bos_bar = cand.bos["bar_idx"]
    i       = cand.bar_idx
    start   = max(0, bos_bar - context_bars)
    end     = min(len(m15_df), i + 30)
    window  = m15_df.iloc[start:end].copy()

    if len(window) < 3:
        return {}

    fib = cand.fib
    bos = cand.bos

    candles = []
    for ts, row in window.iterrows():
        candles.append({
            "time":  int(ts.timestamp()),
            "open":  round(float(row["open"]),  5),
            "high":  round(float(row["high"]),  5),
            "low":   round(float(row["low"]),   5),
            "close": round(float(row["close"]), 5),
        })

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

    fvgs = []
    for fvg in cand.fvgs:
        if fvg.get("mitigated") or fvg.get("direction") != cand.direction:
            continue
        fvgs.append({"top": round(float(fvg["top"]), 5),
                     "bottom": round(float(fvg["bottom"]), 5)})

    sh_bar = bos.get("swing_high_bar")
    sl_bar = bos.get("swing_low_bar")
    sh_ts  = int(m15_df.index[sh_bar].timestamp()) if sh_bar is not None and sh_bar < len(m15_df) else None
    sl_ts  = int(m15_df.index[sl_bar].timestamp()) if sl_bar is not None and sl_bar < len(m15_df) else None

    return {
        "candles":   candles,
        "markers":   sorted(markers, key=lambda m: m["time"]),
        "fvgs":      fvgs,
        "fib": {
            "sl":             round(float(fib.sl),    5),
            "entry":          round(float(fib.entry), 5),
            "tp":             round(float(fib.tp),    5),
            "impulse_high":   round(float(fib.impulse_high), 5),
            "impulse_low":    round(float(fib.impulse_low),  5),
            "swing_high_ts":  sh_ts,
            "swing_low_ts":   sl_ts,
        },
        "bos_level": round(float(bos["level"]), 5),
        "direction": cand.direction,
    }


def _build_chart_html(chart_data: dict, height: int = 520) -> str:
    chart_json = json.dumps(chart_data, cls=_Encoder)
    return f"""
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<script src="https://cdn.jsdelivr.net/npm/lightweight-charts@4.2.0/dist/lightweight-charts.standalone.production.js"></script>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  html, body {{ width: 100%; height: {height}px; background: #131722; overflow: hidden; }}
  #wrap {{ position: absolute; inset: 0; }}
</style>
</head>
<body>
<div id="wrap"></div>
<script>
const CHART_DATA = {chart_json};
const LW = LightweightCharts;

const wrap = document.getElementById('wrap');
const chart = LW.createChart(wrap, {{
  autoSize: true,
  layout: {{
    background: {{ type: LW.ColorType.Solid, color: '#131722' }},
    textColor: '#b2b5be',
    fontSize: 12,
    fontFamily: "'Trebuchet MS', Roboto, Ubuntu, sans-serif",
  }},
  grid: {{
    vertLines: {{ color: 'rgba(42,46,57,0.5)' }},
    horzLines: {{ color: 'rgba(42,46,57,0.5)' }},
  }},
  crosshair: {{
    mode: LW.CrosshairMode.Normal,
    vertLine: {{ color: '#758696', labelBackgroundColor: '#2a2e39' }},
    horzLine: {{ color: '#758696', labelBackgroundColor: '#2a2e39' }},
  }},
  rightPriceScale: {{
    borderColor: '#2a2e39',
    scaleMargins: {{ top: 0.08, bottom: 0.08 }},
    borderVisible: true,
  }},
  timeScale: {{
    borderColor: '#2a2e39',
    timeVisible: true,
    secondsVisible: false,
    fixLeftEdge: true,
    fixRightEdge: true,
    borderVisible: true,
  }},
  handleScroll: true,
  handleScale:  true,
}});

const series = chart.addCandlestickSeries({{
  upColor:         '#26a69a',
  downColor:       '#ef5350',
  borderUpColor:   '#26a69a',
  borderDownColor: '#ef5350',
  wickUpColor:     '#26a69a',
  wickDownColor:   '#ef5350',
  priceFormat: {{ type: 'price', precision: 5, minMove: 0.00001 }},
}});
series.setData(CHART_DATA.candles);

const fib = CHART_DATA.fib;
series.createPriceLine({{ price: fib.sl,    color: 'rgba(255,255,255,0.7)', lineWidth: 1, lineStyle: LW.LineStyle.Solid, axisLabelVisible: true, title: '1' }});
series.createPriceLine({{ price: fib.entry, color: '#f0b429',               lineWidth: 1, lineStyle: LW.LineStyle.Solid, axisLabelVisible: true, title: '0.75' }});
series.createPriceLine({{ price: fib.tp,    color: 'rgba(255,255,255,0.7)', lineWidth: 1, lineStyle: LW.LineStyle.Solid, axisLabelVisible: true, title: '0' }});
series.createPriceLine({{ price: CHART_DATA.bos_level, color: '#29b6f6',    lineWidth: 1, lineStyle: LW.LineStyle.Solid, axisLabelVisible: true, title: 'BOS' }});

if (CHART_DATA.markers && CHART_DATA.markers.length)
  series.setMarkers(CHART_DATA.markers);

function drawOverlays() {{
  const old = wrap.querySelector('canvas.ov');
  if (old) old.remove();
  const canvas = document.createElement('canvas');
  canvas.className = 'ov';
  const dpr  = window.devicePixelRatio || 1;
  const cssW = wrap.clientWidth;
  const cssH = wrap.clientHeight;
  canvas.width  = cssW * dpr;
  canvas.height = cssH * dpr;
  canvas.style.cssText = `position:absolute;top:0;left:0;width:${{cssW}}px;height:${{cssH}}px;pointer-events:none;z-index:3;`;
  wrap.appendChild(canvas);
  const ctx = canvas.getContext('2d');
  ctx.scale(dpr, dpr);
  const ts = chart.timeScale();

  const shTs = fib.swing_high_ts;
  const slTs = fib.swing_low_ts;
  const shX  = shTs ? ts.timeToCoordinate(shTs) : null;
  const slX  = slTs ? ts.timeToCoordinate(slTs) : null;
  let anchorX = 40;
  if (shX !== null && slX !== null) anchorX = Math.min(shX, slX);
  else if (shX !== null)            anchorX = shX;
  else if (slX !== null)            anchorX = slX;
  anchorX = Math.max(anchorX, 16);
  const rightEdge = cssW - 80;

  const priceTop = fib.sl;
  const priceBot = fib.tp;
  const priceMid = (priceTop + priceBot) / 2;

  const fibLevels = [
    {{ label: '1',    price: priceTop, color: 'rgba(255,255,255,0.85)', lw: 1 }},
    {{ label: '0.75', price: fib.entry, color: '#f0b429',               lw: 1.5 }},
    {{ label: '0.5',  price: priceMid,  color: 'rgba(255,255,255,0.45)', lw: 0.75 }},
    {{ label: '0',    price: priceBot,  color: 'rgba(255,255,255,0.85)', lw: 1 }},
  ];

  const yTop = series.priceToCoordinate(priceTop);
  const yBot = series.priceToCoordinate(priceBot);
  const TICK = 8;
  if (yTop !== null && yBot !== null) {{
    ctx.save();
    ctx.strokeStyle = 'rgba(255,255,255,0.75)';
    ctx.lineWidth   = 1.5;
    ctx.beginPath(); ctx.moveTo(anchorX, yTop); ctx.lineTo(anchorX, yBot); ctx.stroke();
    ctx.beginPath(); ctx.moveTo(anchorX - TICK, yTop); ctx.lineTo(anchorX + 4, yTop); ctx.stroke();
    ctx.beginPath(); ctx.moveTo(anchorX - TICK, yBot); ctx.lineTo(anchorX + 4, yBot); ctx.stroke();
    ctx.restore();
  }}

  for (const lv of fibLevels) {{
    const y = series.priceToCoordinate(lv.price);
    if (y === null) continue;
    ctx.save();
    ctx.strokeStyle = lv.color;
    ctx.lineWidth   = lv.lw;
    ctx.beginPath(); ctx.moveTo(anchorX, y); ctx.lineTo(rightEdge, y); ctx.stroke();
    ctx.restore();
    const priceStr = lv.price.toFixed(5);
    const labelStr = `${{lv.label}}  (${{priceStr}})`;
    const labelX   = anchorX + 10;
    const labelY   = y - 4;
    ctx.save();
    ctx.font = "bold 11px 'Trebuchet MS', Arial";
    const tw = ctx.measureText(labelStr).width;
    ctx.fillStyle = 'rgba(19,23,34,0.75)';
    ctx.fillRect(labelX - 2, labelY - 11, tw + 6, 14);
    ctx.fillStyle = lv.color;
    ctx.fillText(labelStr, labelX, labelY);
    ctx.restore();
  }}

  const yEntry = series.priceToCoordinate(fib.entry);
  const ySL    = series.priceToCoordinate(priceTop);
  if (yEntry !== null && ySL !== null) {{
    const top = Math.min(yEntry, ySL);
    const bot = Math.max(yEntry, ySL);
    ctx.save();
    ctx.fillStyle = 'rgba(240,180,41,0.08)';
    ctx.fillRect(anchorX, top, rightEdge - anchorX, bot - top);
    ctx.restore();
  }}

  for (const fvg of (CHART_DATA.fvgs || [])) {{
    const yF1 = series.priceToCoordinate(fvg.top);
    const yF2 = series.priceToCoordinate(fvg.bottom);
    if (yF1 !== null && yF2 !== null && yF2 > yF1) {{
      ctx.fillStyle   = 'rgba(255,235,59,0.10)';
      ctx.strokeStyle = 'rgba(255,235,59,0.3)';
      ctx.lineWidth   = 0.5;
      ctx.fillRect(0, yF1, cssW, yF2 - yF1);
      ctx.strokeRect(0, yF1, cssW, yF2 - yF1);
      ctx.font = '9px Arial';
      ctx.fillStyle = 'rgba(255,235,59,0.55)';
      ctx.fillText('FVG', 6, yF1 + 11);
    }}
  }}
}}

setTimeout(drawOverlays, 250);
chart.timeScale().subscribeVisibleLogicalRangeChange(() => setTimeout(drawOverlays, 50));
window.addEventListener('resize', () => setTimeout(drawOverlays, 100));
</script>
</body>
</html>
"""


# ── Sidebar — inputs ──────────────────────────────────────────────────────────
with st.sidebar:
    st.header("הגדרות סקאן")
    symbol    = st.selectbox("סימבול", config.SYMBOLS, index=0)
    default_to   = pd.Timestamp.today().normalize()
    default_from = default_to - pd.Timedelta(days=55)
    date_from = st.date_input("מתאריך", value=default_from)
    date_to   = st.date_input("עד תאריך", value=default_to)
    max_setups = st.slider("מקסימום סטאפים", 5, 100, 25)
    scan_btn  = st.button("🔍 סרוק סטאפים", type="primary", use_container_width=True)

    if "scan_decisions" in st.session_state and st.session_state["scan_decisions"]:
        st.markdown("---")
        decisions = st.session_state["scan_decisions"]
        taken  = sum(1 for d in decisions.values() if d == "y")
        skipped = sum(1 for d in decisions.values() if d == "n")
        st.metric("נלקחו", taken)
        st.metric("דולגו", skipped)

# ── Run scan ──────────────────────────────────────────────────────────────────
if scan_btn:
    with st.spinner(f"טוען נתונים ומריץ סקאן על {symbol}…"):
        try:
            m15 = get_ohlcv(symbol, "M15", str(date_from), str(date_to))
            h1  = get_ohlcv(symbol, "H1",  str(date_from), str(date_to))
            if m15 is None or len(m15) < 50:
                st.error("לא מספיק נתונים.")
                st.stop()

            candidates = scan_setups(m15, h1, symbol)
            # Sort by score, take top N
            scored = sorted(candidates, key=lambda c: (-_score(c), c.bar_idx))
            top = scored[:max_setups]

            st.session_state["scan_candidates"] = top
            st.session_state["scan_m15"]        = m15
            st.session_state["scan_idx"]        = 0
            st.session_state["scan_decisions"]  = {}
            st.session_state["scan_symbol"]     = symbol
            st.rerun()
        except Exception as e:
            st.error(f"שגיאה: {e}")
            st.stop()

# ── Show setups ───────────────────────────────────────────────────────────────
if "scan_candidates" not in st.session_state:
    st.info("בחר פרמטרים בסרגל הצד ולחץ **סרוק סטאפים**.")
    st.stop()

candidates = st.session_state["scan_candidates"]
m15        = st.session_state["scan_m15"]
idx        = st.session_state["scan_idx"]
decisions  = st.session_state["scan_decisions"]
sym        = st.session_state["scan_symbol"]

total = len(candidates)

if total == 0:
    st.warning("לא נמצאו סטאפים בטווח התאריכים שנבחר.")
    st.stop()

# ── Navigation bar ────────────────────────────────────────────────────────────
nav_col1, nav_col2, nav_col3, nav_col4 = st.columns([1, 2, 1, 3])
with nav_col1:
    if st.button("◀ הקודם", disabled=(idx == 0)):
        st.session_state["scan_idx"] = idx - 1
        st.rerun()
with nav_col2:
    st.markdown(f"### סטאפ {idx + 1} / {total}")
with nav_col3:
    if st.button("הבא ▶", disabled=(idx >= total - 1)):
        st.session_state["scan_idx"] = idx + 1
        st.rerun()
with nav_col4:
    # Jump to setup number
    jump = st.number_input("קפוץ לסטאפ", min_value=1, max_value=total,
                           value=idx + 1, step=1, label_visibility="collapsed")
    if jump - 1 != idx:
        st.session_state["scan_idx"] = jump - 1
        st.rerun()

# ── Current setup info ────────────────────────────────────────────────────────
cand = candidates[idx]
fib  = cand.fib
bos  = cand.bos
rr   = fib.tp_distance / fib.sl_distance if fib.sl_distance > 0 else 0

direction_label = "▲ LONG" if cand.direction == "bull" else "▼ SHORT"
direction_color = "green" if cand.direction == "bull" else "red"

info_col1, info_col2, info_col3, info_col4, info_col5 = st.columns(5)
info_col1.metric("כיוון",   direction_label)
info_col2.metric("Entry",   f"{fib.entry:.5f}")
info_col3.metric("SL",      f"{fib.sl:.5f}")
info_col4.metric("TP",      f"{fib.tp:.5f}")
info_col5.metric("R:R",     f"{rr:.2f}:1")

badges = []
if cand.has_fvg_near_entry:
    badges.append("🟡 FVG ליד כניסה")
if cand.all_conditions_met:
    badges.append("✅ כל 5 התנאים")
else:
    badges.append("⚪ תנאים 1-3 בלבד")

st.markdown("  ".join(badges))
st.markdown(f"*BOS @ `{bos['level']:.5f}` — {str(bos['timestamp'])[:16]}*")

# ── Chart ─────────────────────────────────────────────────────────────────────
chart_data = _build_chart_data(m15, cand)
if chart_data:
    chart_html = _build_chart_html(chart_data, height=520)
    components.html(chart_html, height=520, scrolling=False)
else:
    st.warning("לא ניתן לבנות את הגרף לסטאפ זה.")

# ── Decision buttons ──────────────────────────────────────────────────────────
st.markdown("---")
current_decision = decisions.get(idx)

btn_col1, btn_col2, btn_col3 = st.columns([2, 2, 6])

with btn_col1:
    yes_type = "primary" if current_decision == "y" else "secondary"
    if st.button("✅  YES — לוקח", type=yes_type, use_container_width=True):
        st.session_state["scan_decisions"][idx] = "y"
        if idx < total - 1:
            st.session_state["scan_idx"] = idx + 1
        st.rerun()

with btn_col2:
    no_type = "primary" if current_decision == "n" else "secondary"
    if st.button("❌  NO — מדלג", type=no_type, use_container_width=True):
        st.session_state["scan_decisions"][idx] = "n"
        if idx < total - 1:
            st.session_state["scan_idx"] = idx + 1
        st.rerun()

if current_decision:
    label = "✅ נלקח" if current_decision == "y" else "❌ דולג"
    st.info(f"ההחלטה על סטאפ זה: **{label}**")

# ── Progress bar ──────────────────────────────────────────────────────────────
decided_count = len(decisions)
if decided_count > 0:
    st.progress(decided_count / total,
                text=f"נסקרו {decided_count}/{total} סטאפים")

# ── Mini decision summary ──────────────────────────────────────────────────────
if decided_count >= 3:
    st.markdown("---")
    st.subheader("📋 סיכום החלטות עד כה")
    rows = []
    for i, c in enumerate(candidates):
        if i not in decisions:
            continue
        f = c.fib
        r = f.tp_distance / f.sl_distance if f.sl_distance > 0 else 0
        rows.append({
            "#":      i + 1,
            "כיוון":  "▲ LONG" if c.direction == "bull" else "▼ SHORT",
            "זמן":    str(c.bar_time)[:16],
            "Entry":  f"{f.entry:.5f}",
            "R:R":    f"{r:.2f}",
            "החלטה":  "✅ YES" if decisions[i] == "y" else "❌ NO",
        })
    if rows:
        st.dataframe(pd.DataFrame(rows), use_container_width=True, height=200)
