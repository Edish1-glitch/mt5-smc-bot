"""
web/pages/1_Backtest.py — Run a full backtest and display results.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import json
import streamlit as st
import streamlit.components.v1 as components
import pandas as pd
import numpy as np
import plotly.graph_objects as go

st.set_page_config(page_title="Backtest", layout="wide", page_icon="🔬",
                   initial_sidebar_state="collapsed")

from web.mobile_css import inject_mobile_css
inject_mobile_css()

st.title("🔬 Run Backtest")

import config
from data.fetcher import get_ohlcv
from backtest.engine import run_backtest as _run_backtest
from backtest.results import compute_stats, equity_curve


@st.cache_data(show_spinner=False)
def _cached_backtest(symbol, date_from_str, date_to_str, risk_trade, capital, compound, risk_pct):
    """Cache backtest results — same params = instant re-run."""
    m15 = get_ohlcv(symbol, "M15", date_from_str, date_to_str)
    h1  = get_ohlcv(symbol, "H1",  date_from_str, date_to_str)
    if m15 is None or len(m15) < 50:
        return None, None, None
    trades = _run_backtest(
        m15, h1, symbol,
        risk_per_trade=risk_trade,
        compound=compound,
        initial_capital=capital,
        risk_pct=risk_pct,
    )
    return trades, m15, h1

# ── Sidebar — inputs ──────────────────────────────────────────────────────────
with st.sidebar:
    st.header("הגדרות")
    symbol     = st.selectbox("סימבול", config.SYMBOLS, index=0)
    default_to   = pd.Timestamp.today().normalize()
    default_from = default_to - pd.Timedelta(days=730)
    date_from  = st.date_input("מתאריך", value=default_from)
    date_to    = st.date_input("עד תאריך", value=default_to)
    capital    = st.number_input("הון התחלתי ($)", value=config.INITIAL_CAPITAL,
                                 step=1000, min_value=1000)

    compound   = st.checkbox("📈 ריבית דריבית (compound)",
                             value=False,
                             help="סיכון = % מההון הנוכחי. ככל שהתיק גדל, גם הסיכון גדל.")
    if compound:
        risk_pct = st.number_input("סיכון לעסקה (%)", value=0.5,
                                   step=0.1, min_value=0.1, max_value=10.0,
                                   format="%.2f")
        risk_trade = config.RISK_PER_TRADE  # ignored
    else:
        risk_pct = 0.5  # ignored
        risk_trade = st.number_input("סיכון לעסקה ($)", value=config.RISK_PER_TRADE,
                                     step=50, min_value=50)

    run_btn    = st.button("▶  הרץ בקטסט", type="primary", use_container_width=True)

# ── Run ───────────────────────────────────────────────────────────────────────
if run_btn:
    with st.spinner(f"טוען נתונים ומריץ בקטסט על {symbol}… (עלול לקחת כמה דקות בפעם הראשונה)"):
        try:
            trades, m15, h1 = _cached_backtest(symbol, str(date_from), str(date_to), risk_trade, capital, compound, risk_pct)
            if trades is None:
                st.error("לא מספיק נתוני M15. נסה טווח תאריכים רחב יותר.")
                st.stop()
            stats  = compute_stats(trades, capital)

            st.session_state["bt_trades"]    = trades
            st.session_state["bt_stats"]     = stats
            st.session_state["bt_capital"]   = capital
            st.session_state["bt_symbol"]    = symbol
            st.session_state["bt_m15"]       = m15
            st.session_state["bt_trade_idx"] = 0
        except Exception as e:
            st.error(f"שגיאה: {e}")
            st.stop()

# ── Display results ───────────────────────────────────────────────────────────
if "bt_stats" not in st.session_state:
    st.info("בחר פרמטרים בסרגל הצד ולחץ **הרץ בקטסט**.")
    st.stop()

stats   = st.session_state["bt_stats"]
trades  = st.session_state["bt_trades"]
capital = st.session_state["bt_capital"]
symbol  = st.session_state["bt_symbol"]

if stats.get("total_trades", 0) == 0:
    st.warning("לא נמצאו עסקאות. נסה טווח תאריכים רחב יותר.")
    st.stop()

# ── Key metrics row ───────────────────────────────────────────────────────────
st.markdown("---")
c1, c2, c3, c4, c5, c6 = st.columns(6)
c1.metric("עסקאות סה״כ",    stats["total_trades"])
c2.metric("Win Rate",
          f"{stats['win_rate_pct']}%",
          delta=f"{stats['wins']}W / {stats['losses']}L")
c3.metric("Profit Factor",  f"{stats['profit_factor']}")
c4.metric("Net P&L",        f"${stats['net_pnl_usd']:,.0f}",
          delta=f"${stats['net_pnl_usd']:,.0f}",
          delta_color="normal")
c5.metric("Max Drawdown",   f"{stats['max_dd_pct']:.1f}%")
c6.metric("Avg R:R",        f"{stats['avg_rr']:.2f}")

# ── Equity curve ──────────────────────────────────────────────────────────────
st.markdown("---")
st.subheader("📈 Equity Curve")

eq = equity_curve(trades, capital)
fig = go.Figure()
fig.add_trace(go.Scatter(
    x=eq.index, y=eq.values,
    mode="lines",
    line=dict(color="#26a69a", width=2),
    fill="tozeroy",
    fillcolor="rgba(38,166,154,0.1)",
    name="Equity",
))
# Highlight drawdown
peak = np.maximum.accumulate(eq.values)
fig.add_trace(go.Scatter(
    x=eq.index, y=peak,
    mode="lines",
    line=dict(color="rgba(255,255,255,0.2)", width=1, dash="dot"),
    name="Peak",
))
fig.update_layout(
    paper_bgcolor="#131722",
    plot_bgcolor="#131722",
    font=dict(color="#d1d4dc"),
    xaxis=dict(gridcolor="#1e2130", showgrid=True),
    yaxis=dict(gridcolor="#1e2130", showgrid=True, tickprefix="$"),
    legend=dict(bgcolor="#1e2130"),
    height=350,
    margin=dict(l=60, r=20, t=20, b=40),
)
st.plotly_chart(fig, use_container_width=True)

# ── Stats table ───────────────────────────────────────────────────────────────
st.markdown("---")
st.subheader("📋 סטטיסטיקות מלאות")

left, right = st.columns(2)
stat_rows = [
    ("עסקאות סגורות",     f"{stats['total_trades']}"),
    ("נצחונות",            f"{stats['wins']}"),
    ("הפסדים",             f"{stats['losses']}"),
    ("עסקאות פתוחות",     f"{stats.get('open_trades', 0)}"),
    ("Win Rate",           f"{stats['win_rate_pct']}%"),
    ("Profit Factor",      f"{stats['profit_factor']}"),
    ("Avg R:R",            f"{stats['avg_rr']}"),
    ("Net P&L",            f"${stats['net_pnl_usd']:,.2f}"),
    ("Gross Profit",       f"${stats['gross_profit']:,.2f}"),
    ("Gross Loss",         f"${stats['gross_loss']:,.2f}"),
    ("ממוצע נצחון",        f"${stats['avg_win_usd']:,.2f}"),
    ("ממוצע הפסד",         f"${stats['avg_loss_usd']:,.2f}"),
    ("Expectancy",         f"${stats['expectancy_usd']:,.2f}"),
    ("Max Drawdown ($)",   f"${stats['max_dd_usd']:,.2f}"),
    ("Max Drawdown (%)",   f"{stats['max_dd_pct']:.2f}%"),
    ("Final Equity",       f"${stats['final_equity']:,.2f}"),
]

mid = len(stat_rows) // 2
with left:
    for label, val in stat_rows[:mid]:
        col_a, col_b = st.columns([2, 1])
        col_a.markdown(f"**{label}**")
        col_b.markdown(val)
with right:
    for label, val in stat_rows[mid:]:
        col_a, col_b = st.columns([2, 1])
        col_a.markdown(f"**{label}**")
        col_b.markdown(val)

# ── Trades table ──────────────────────────────────────────────────────────────
st.markdown("---")
st.subheader("📑 פירוט עסקאות")

closed = [t for t in trades if t.result in ("win", "loss")]
if closed:
    rows = []
    for t in closed:
        rows.append({
            "כיוון":      "▲ LONG" if t.direction == "bull" else "▼ SHORT",
            "כניסה":      str(t.entry_time)[:16],
            "יציאה":      str(t.exit_time)[:16] if t.exit_time else "—",
            "מחיר כניסה": f"{t.entry_price:.5f}",
            "SL":          f"{t.sl_price:.5f}",
            "TP":          f"{t.tp_price:.5f}",
            "R:R":         f"{t.risk_reward:.2f}",
            "P&L ($)":     f"{t.pnl_usd:+.2f}",
            "תוצאה":       "✅ WIN" if t.result == "win" else "❌ LOSS",
        })
    df = pd.DataFrame(rows)

    def color_result(val):
        if "WIN" in str(val):
            return "color: #26a69a; font-weight: bold"
        if "LOSS" in str(val):
            return "color: #ef5350; font-weight: bold"
        if "LONG" in str(val):
            return "color: #26a69a"
        if "SHORT" in str(val):
            return "color: #ef5350"
        if str(val).startswith("+"):
            return "color: #26a69a"
        if str(val).startswith("-"):
            return "color: #ef5350"
        return ""

    styled = df.style.applymap(color_result)
    st.dataframe(styled, use_container_width=True, height=400)
else:
    st.info("אין עסקאות סגורות להצגה.")

# ── Visual Trade Charts ──────────────────────────────────────────────────────
if closed:
    st.markdown("---")
    st.subheader("📊 ניתוח ויזואלי של עסקאות")

    # Store m15 in session for charting
    if "bt_m15" not in st.session_state:
        # Re-fetch — already cached by st.cache_data so instant
        _t, m15_chart, _h = _cached_backtest(symbol, str(date_from), str(date_to), risk_trade, capital, compound, risk_pct)
        st.session_state["bt_m15"] = m15_chart
    else:
        m15_chart = st.session_state["bt_m15"]

    # Trade selector
    trade_labels = [
        f"#{i+1}  {'▲' if t.direction == 'bull' else '▼'}  "
        f"{'WIN' if t.result == 'win' else 'LOSS'}  "
        f"{t.pnl_usd:+.0f}$  |  {str(t.entry_time)[:16]}"
        for i, t in enumerate(closed)
    ]

    nav_c1, nav_c2, nav_c3 = st.columns([1, 4, 1])
    tidx = st.session_state.get("bt_trade_idx", 0)
    with nav_c1:
        if st.button("◀ הקודם", disabled=(tidx == 0), key="prev_trade"):
            st.session_state["bt_trade_idx"] = tidx - 1
            st.rerun()
    with nav_c3:
        if st.button("הבא ▶", disabled=(tidx >= len(closed) - 1), key="next_trade"):
            st.session_state["bt_trade_idx"] = tidx + 1
            st.rerun()
    with nav_c2:
        selected = st.selectbox(
            "בחר עסקה", trade_labels, index=tidx, key="trade_select",
            label_visibility="collapsed",
        )
        new_idx = trade_labels.index(selected)
        if new_idx != tidx:
            st.session_state["bt_trade_idx"] = new_idx
            st.rerun()

    tidx = st.session_state.get("bt_trade_idx", 0)
    trade = closed[tidx]

    # Build chart data
    def _build_trade_chart_data(m15_df, t, context_bars=80):
        entry_loc = m15_df.index.searchsorted(t.entry_time)
        if t.exit_time is not None:
            exit_loc = m15_df.index.searchsorted(t.exit_time) + 10
        else:
            exit_loc = min(entry_loc + 100, len(m15_df))

        # Extend window left to include impulse swing candles
        impulse_start = entry_loc
        if t.impulse_high_time is not None:
            sh_loc = m15_df.index.searchsorted(t.impulse_high_time)
            impulse_start = min(impulse_start, sh_loc)
        if t.impulse_low_time is not None:
            sl_loc = m15_df.index.searchsorted(t.impulse_low_time)
            impulse_start = min(impulse_start, sl_loc)

        start = max(0, min(entry_loc - context_bars, impulse_start - 10))
        window = m15_df.iloc[start:exit_loc]

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

        # Impulse swing high marker
        if t.impulse_high_time is not None:
            sh_unix = int(t.impulse_high_time.timestamp())
            if candles and sh_unix >= candles[0]["time"] and sh_unix <= candles[-1]["time"]:
                markers.append({
                    "time":     sh_unix,
                    "position": "aboveBar",
                    "color":    "#ff9800",
                    "shape":    "circle",
                    "text":     f"SH {t.impulse_high:.5f}",
                })

        # Impulse swing low marker
        if t.impulse_low_time is not None:
            sl_unix = int(t.impulse_low_time.timestamp())
            if candles and sl_unix >= candles[0]["time"] and sl_unix <= candles[-1]["time"]:
                markers.append({
                    "time":     sl_unix,
                    "position": "belowBar",
                    "color":    "#ff9800",
                    "shape":    "circle",
                    "text":     f"SL {t.impulse_low:.5f}",
                })

        # Entry marker
        entry_unix = int(t.entry_time.timestamp())
        if candles and entry_unix >= candles[0]["time"] and entry_unix <= candles[-1]["time"]:
            markers.append({
                "time":     entry_unix,
                "position": "belowBar" if t.direction == "bull" else "aboveBar",
                "color":    "#00bcd4",
                "shape":    "arrowUp" if t.direction == "bull" else "arrowDown",
                "text":     "ENTRY",
            })

        # Exit marker
        if t.exit_time is not None:
            exit_unix = int(t.exit_time.timestamp())
            exit_color = "#26a69a" if t.result == "win" else "#ef5350"
            if candles and exit_unix >= candles[0]["time"] and exit_unix <= candles[-1]["time"]:
                markers.append({
                    "time":     exit_unix,
                    "position": "aboveBar" if t.direction == "bull" else "belowBar",
                    "color":    exit_color,
                    "shape":    "arrowDown" if t.direction == "bull" else "arrowUp",
                    "text":     "EXIT ✅" if t.result == "win" else "EXIT ❌",
                })

        # Impulse swing timestamps for fib drawing
        sh_ts = int(t.impulse_high_time.timestamp()) if t.impulse_high_time is not None else None
        sl_ts = int(t.impulse_low_time.timestamp()) if t.impulse_low_time is not None else None

        return {
            "candles": candles,
            "markers": sorted(markers, key=lambda m: m["time"]),
            "entry":   round(t.entry_price, 5),
            "sl":      round(t.sl_price, 5),
            "tp":      round(t.tp_price, 5),
            "impulse_high": round(t.impulse_high, 5),
            "impulse_low":  round(t.impulse_low, 5),
            "impulse_high_ts": sh_ts,
            "impulse_low_ts":  sl_ts,
            "direction": t.direction,
            "result":  t.result,
        }

    def _build_trade_chart_html(chart_data, height=550):
        chart_json = json.dumps(chart_data)
        result_color = "#26a69a" if chart_data["result"] == "win" else "#ef5350"
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
const D = {chart_json};
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
  }},
  timeScale: {{
    borderColor: '#2a2e39',
    timeVisible: true,
    secondsVisible: false,
    fixLeftEdge: true,
    fixRightEdge: true,
  }},
  handleScroll: true,
  handleScale: true,
}});

const series = chart.addCandlestickSeries({{
  upColor: '#26a69a', downColor: '#ef5350',
  borderUpColor: '#26a69a', borderDownColor: '#ef5350',
  wickUpColor: '#26a69a', wickDownColor: '#ef5350',
  priceFormat: {{ type: 'price', precision: 5, minMove: 0.00001 }},
}});
series.setData(D.candles);

// Fib levels
series.createPriceLine({{ price: D.entry, color: '#f0b429', lineWidth: 2, lineStyle: LW.LineStyle.Solid, axisLabelVisible: true, title: 'Entry 75%' }});
series.createPriceLine({{ price: D.sl,    color: '#ef5350', lineWidth: 2, lineStyle: LW.LineStyle.Dashed, axisLabelVisible: true, title: 'SL 100%' }});
series.createPriceLine({{ price: D.tp,    color: '#26a69a', lineWidth: 2, lineStyle: LW.LineStyle.Dashed, axisLabelVisible: true, title: 'TP 0%' }});

// 50% level
const mid = (D.sl + D.tp) / 2;
series.createPriceLine({{ price: mid, color: 'rgba(255,255,255,0.3)', lineWidth: 1, lineStyle: LW.LineStyle.Dotted, axisLabelVisible: true, title: '50%' }});

// 25% level
const q25 = D.direction === 'bull' ? D.tp - 0.25 * (D.tp - D.sl) : D.sl + 0.25 * (D.tp - D.sl);
series.createPriceLine({{ price: q25, color: 'rgba(255,255,255,0.2)', lineWidth: 1, lineStyle: LW.LineStyle.Dotted, axisLabelVisible: false, title: '25%' }});

if (D.markers && D.markers.length) series.setMarkers(D.markers);

// Draw overlays: fib ruler, SL/TP zones
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

  const yEntry = series.priceToCoordinate(D.entry);
  const ySL    = series.priceToCoordinate(D.sl);
  const yTP    = series.priceToCoordinate(D.tp);
  const rightEdge = cssW - 60;

  // Fib ruler: vertical line from impulse swing high candle to swing low candle
  const shTs = D.impulse_high_ts;
  const slTs = D.impulse_low_ts;
  if (shTs && slTs) {{
    const shX = ts.timeToCoordinate(shTs);
    const slX = ts.timeToCoordinate(slTs);
    const yHigh = series.priceToCoordinate(D.impulse_high);
    const yLow  = series.priceToCoordinate(D.impulse_low);
    const anchorX = Math.max(Math.min(shX || 40, slX || 40), 16);

    if (yHigh !== null && yLow !== null) {{
      // Vertical fib ruler line
      ctx.save();
      ctx.strokeStyle = '#ff9800';
      ctx.lineWidth = 2;
      ctx.setLineDash([6, 3]);
      ctx.beginPath(); ctx.moveTo(anchorX, yHigh); ctx.lineTo(anchorX, yLow); ctx.stroke();
      // Tick marks
      ctx.setLineDash([]);
      const TICK = 10;
      ctx.beginPath(); ctx.moveTo(anchorX - TICK, yHigh); ctx.lineTo(anchorX + TICK, yHigh); ctx.stroke();
      ctx.beginPath(); ctx.moveTo(anchorX - TICK, yLow);  ctx.lineTo(anchorX + TICK, yLow);  ctx.stroke();
      ctx.restore();

      // Fib level labels on the ruler
      const fibLevels = [
        {{ label: '0%', price: D.direction === 'bull' ? D.impulse_high : D.impulse_low, color: '#26a69a' }},
        {{ label: '25%', price: D.direction === 'bull' ? D.impulse_high - 0.25*(D.impulse_high-D.impulse_low) : D.impulse_low + 0.25*(D.impulse_high-D.impulse_low), color: 'rgba(255,255,255,0.4)' }},
        {{ label: '50%', price: (D.impulse_high + D.impulse_low) / 2, color: 'rgba(255,255,255,0.5)' }},
        {{ label: '75%', price: D.entry, color: '#f0b429' }},
        {{ label: '100%', price: D.direction === 'bull' ? D.impulse_low : D.impulse_high, color: '#ef5350' }},
      ];

      for (const lv of fibLevels) {{
        const y = series.priceToCoordinate(lv.price);
        if (y === null) continue;
        // Horizontal line from ruler to right
        ctx.save();
        ctx.strokeStyle = lv.color;
        ctx.lineWidth = lv.label === '75%' ? 1.5 : 0.7;
        ctx.globalAlpha = lv.label === '75%' || lv.label === '100%' || lv.label === '0%' ? 0.8 : 0.4;
        ctx.setLineDash(lv.label === '75%' ? [] : [4, 4]);
        ctx.beginPath(); ctx.moveTo(anchorX, y); ctx.lineTo(rightEdge, y); ctx.stroke();
        ctx.restore();
        // Label
        const labelStr = `${{lv.label}}  (${{lv.price.toFixed(5)}})`;
        ctx.save();
        ctx.font = "bold 11px 'Trebuchet MS', Arial";
        const tw = ctx.measureText(labelStr).width;
        ctx.fillStyle = 'rgba(19,23,34,0.8)';
        ctx.fillRect(anchorX + 6, y - 13, tw + 6, 16);
        ctx.fillStyle = lv.color;
        ctx.fillText(labelStr, anchorX + 8, y - 1);
        ctx.restore();
      }}

      // Connecting lines from swing candles to ruler
      if (shX !== null) {{
        ctx.save();
        ctx.strokeStyle = '#ff9800';
        ctx.lineWidth = 1;
        ctx.globalAlpha = 0.5;
        ctx.setLineDash([3, 3]);
        ctx.beginPath(); ctx.moveTo(shX, yHigh); ctx.lineTo(anchorX, yHigh); ctx.stroke();
        ctx.restore();
      }}
      if (slX !== null) {{
        ctx.save();
        ctx.strokeStyle = '#ff9800';
        ctx.lineWidth = 1;
        ctx.globalAlpha = 0.5;
        ctx.setLineDash([3, 3]);
        ctx.beginPath(); ctx.moveTo(slX, yLow); ctx.lineTo(anchorX, yLow); ctx.stroke();
        ctx.restore();
      }}
    }}
  }}

  // SL zone (entry to SL) — red tint
  if (yEntry !== null && ySL !== null) {{
    const top = Math.min(yEntry, ySL);
    const bot = Math.max(yEntry, ySL);
    ctx.fillStyle = 'rgba(239,83,80,0.07)';
    ctx.fillRect(0, top, rightEdge, bot - top);
  }}

  // TP zone (entry to TP) — green tint
  if (yEntry !== null && yTP !== null) {{
    const top = Math.min(yEntry, yTP);
    const bot = Math.max(yEntry, yTP);
    ctx.fillStyle = 'rgba(38,166,154,0.07)';
    ctx.fillRect(0, top, rightEdge, bot - top);
  }}
}}

setTimeout(drawOverlays, 250);
chart.timeScale().subscribeVisibleLogicalRangeChange(() => setTimeout(drawOverlays, 50));
window.addEventListener('resize', () => setTimeout(drawOverlays, 100));
</script>
</body>
</html>
"""

    chart_data = _build_trade_chart_data(m15_chart, trade)
    result_emoji = "✅" if trade.result == "win" else "❌"
    dir_text = "LONG ▲" if trade.direction == "bull" else "SHORT ▼"
    st.markdown(
        f"**{dir_text}**  |  {result_emoji} **{trade.result.upper()}**  |  "
        f"P&L: **{trade.pnl_usd:+.2f}$**  |  R:R: **{trade.risk_reward:.2f}**  |  "
        f"Entry: `{trade.entry_price:.5f}`  SL: `{trade.sl_price:.5f}`  TP: `{trade.tp_price:.5f}`"
    )
    components.html(_build_trade_chart_html(chart_data), height=560)
