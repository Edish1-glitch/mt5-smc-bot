"""
web/pages/3_Compare.py — Compare the SMC strategy across multiple symbols.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go

st.set_page_config(page_title="Compare", layout="wide", page_icon="📊",
                   initial_sidebar_state="collapsed")

from web.mobile_css import inject_mobile_css
inject_mobile_css()

st.title("📊 Compare — השוואת סימבולים")

import config
from data.fetcher import get_ohlcv
from backtest.engine import run_backtest
from backtest.results import compute_stats, equity_curve

# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.header("הגדרות")
    symbols    = st.multiselect("סימבולים", config.SYMBOLS,
                                default=["EURUSD", "GBPUSD"])
    default_to   = pd.Timestamp.today().normalize()
    default_from = default_to - pd.Timedelta(days=55)
    date_from  = st.date_input("מתאריך", value=default_from)
    date_to    = st.date_input("עד תאריך", value=default_to)
    capital    = st.number_input("הון התחלתי ($)", value=config.INITIAL_CAPITAL,
                                 step=1000, min_value=1000)
    risk_trade = st.number_input("סיכון לעסקה ($)", value=config.RISK_PER_TRADE,
                                 step=50, min_value=50)
    run_btn    = st.button("▶  הרץ השוואה", type="primary", use_container_width=True)

# ── Run ───────────────────────────────────────────────────────────────────────
if run_btn:
    if len(symbols) < 1:
        st.error("בחר לפחות סימבול אחד.")
        st.stop()

    results = {}
    progress = st.progress(0, text="מריץ בקטסטים…")

    for i, sym in enumerate(symbols):
        progress.progress((i) / len(symbols), text=f"מריץ {sym}…")
        try:
            m15 = get_ohlcv(sym, "M15", str(date_from), str(date_to))
            h1  = get_ohlcv(sym, "H1",  str(date_from), str(date_to))
            if m15 is None or len(m15) < 50:
                st.warning(f"{sym}: לא מספיק נתונים, מדלג.")
                continue
            trades = run_backtest(m15, h1, sym, risk_per_trade=risk_trade)
            stats  = compute_stats(trades, capital)
            eq     = equity_curve(trades, capital)
            results[sym] = {"stats": stats, "trades": trades, "equity": eq}
        except Exception as e:
            st.warning(f"{sym}: שגיאה — {e}")

    progress.progress(1.0, text="סיום!")

    if results:
        st.session_state["compare_results"]  = results
        st.session_state["compare_capital"]  = capital

# ── Display ───────────────────────────────────────────────────────────────────
if "compare_results" not in st.session_state:
    st.info("בחר סימבולים בסרגל הצד ולחץ **הרץ השוואה**.")
    st.stop()

results = st.session_state["compare_results"]
capital = st.session_state["compare_capital"]

if not results:
    st.warning("לא היו תוצאות.")
    st.stop()

# ── Comparison table ──────────────────────────────────────────────────────────
st.markdown("---")
st.subheader("📋 טבלת השוואה")

rows = []
for sym, res in results.items():
    s = res["stats"]
    if s.get("total_trades", 0) == 0:
        rows.append({"סימבול": sym, "עסקאות": 0,
                     "Win Rate": "—", "Profit Factor": "—",
                     "Net P&L ($)": "—", "Max DD (%)": "—",
                     "Avg R:R": "—", "Final Equity ($)": "—"})
    else:
        rows.append({
            "סימבול":          sym,
            "עסקאות":          s["total_trades"],
            "Win Rate":        f"{s['win_rate_pct']}%",
            "Profit Factor":   s["profit_factor"],
            "Net P&L ($)":     s["net_pnl_usd"],
            "Max DD (%)":      s["max_dd_pct"],
            "Avg R:R":         s["avg_rr"],
            "Final Equity ($)":s["final_equity"],
        })

df = pd.DataFrame(rows).set_index("סימבול")

# Highlight best/worst Net P&L
def highlight_pnl(row):
    styles = [""] * len(row)
    return styles

st.dataframe(df, use_container_width=True)

# Best / worst callouts
valid = {sym: res for sym, res in results.items()
         if res["stats"].get("total_trades", 0) > 0}
if valid:
    best_sym  = max(valid, key=lambda s: valid[s]["stats"]["net_pnl_usd"])
    worst_sym = min(valid, key=lambda s: valid[s]["stats"]["net_pnl_usd"])
    c1, c2 = st.columns(2)
    c1.success(f"**הכי טוב**: {best_sym} — "
               f"${valid[best_sym]['stats']['net_pnl_usd']:,.0f} | "
               f"WR {valid[best_sym]['stats']['win_rate_pct']}%")
    c2.error(f"**הכי גרוע**: {worst_sym} — "
             f"${valid[worst_sym]['stats']['net_pnl_usd']:,.0f} | "
             f"WR {valid[worst_sym]['stats']['win_rate_pct']}%")

# ── Equity curves overlay ──────────────────────────────────────────────────────
st.markdown("---")
st.subheader("📈 Equity Curves")

colors = ["#26a69a", "#ef5350", "#29b6f6", "#ffd600",
          "#e040fb", "#4caf50", "#ff7043"]
fig = go.Figure()
for i, (sym, res) in enumerate(results.items()):
    eq = res["equity"]
    if eq is None or len(eq) < 2:
        continue
    fig.add_trace(go.Scatter(
        x=eq.index, y=eq.values,
        mode="lines",
        name=sym,
        line=dict(color=colors[i % len(colors)], width=2),
    ))

# Add horizontal baseline
fig.add_hline(y=capital, line=dict(color="rgba(255,255,255,0.2)",
              width=1, dash="dot"), annotation_text="התחלה")

fig.update_layout(
    paper_bgcolor="#131722",
    plot_bgcolor="#131722",
    font=dict(color="#d1d4dc"),
    xaxis=dict(gridcolor="#1e2130", showgrid=True),
    yaxis=dict(gridcolor="#1e2130", showgrid=True, tickprefix="$"),
    legend=dict(bgcolor="#1e2130"),
    height=400,
    margin=dict(l=60, r=20, t=20, b=40),
)
st.plotly_chart(fig, use_container_width=True)

# ── Per-symbol detail ─────────────────────────────────────────────────────────
st.markdown("---")
st.subheader("🔍 פירוט לכל סימבול")

tabs = st.tabs(list(results.keys()))
for tab, (sym, res) in zip(tabs, results.items()):
    with tab:
        s = res["stats"]
        if s.get("total_trades", 0) == 0:
            st.warning("אין עסקאות.")
            continue

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("עסקאות",        s["total_trades"])
        m2.metric("Win Rate",       f"{s['win_rate_pct']}%")
        m3.metric("Profit Factor",  s["profit_factor"])
        m4.metric("Net P&L",        f"${s['net_pnl_usd']:,.0f}")

        closed = [t for t in res["trades"] if t.result in ("win", "loss")]
        if closed:
            rows = []
            for t in closed:
                rows.append({
                    "כיוון":  "▲ LONG" if t.direction == "bull" else "▼ SHORT",
                    "כניסה":  str(t.entry_time)[:16],
                    "יציאה":  str(t.exit_time)[:16] if t.exit_time else "—",
                    "P&L":    f"{t.pnl_usd:+.2f}",
                    "תוצאה":  "✅ WIN" if t.result == "win" else "❌ LOSS",
                })
            st.dataframe(pd.DataFrame(rows), use_container_width=True, height=250)
