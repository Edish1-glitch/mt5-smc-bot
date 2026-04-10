"""
web/pages/1_Backtest.py — Run a full backtest and display results.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go

st.set_page_config(page_title="Backtest", layout="wide", page_icon="🔬")
st.title("🔬 Run Backtest")

import config
from data.fetcher import get_ohlcv
from backtest.engine import run_backtest as _run_backtest
from backtest.results import compute_stats, equity_curve


@st.cache_data(show_spinner=False)
def _cached_backtest(symbol, date_from_str, date_to_str, risk_trade):
    """Cache backtest results — same params = instant re-run."""
    m15 = get_ohlcv(symbol, "M15", date_from_str, date_to_str)
    h1  = get_ohlcv(symbol, "H1",  date_from_str, date_to_str)
    if m15 is None or len(m15) < 50:
        return None, None, None
    trades = _run_backtest(m15, h1, symbol, risk_per_trade=risk_trade)
    return trades, m15, h1

# ── Sidebar — inputs ──────────────────────────────────────────────────────────
with st.sidebar:
    st.header("הגדרות")
    symbol     = st.selectbox("סימבול", config.SYMBOLS, index=0)
    date_from  = st.date_input("מתאריך", value=pd.Timestamp("2024-01-01"))
    date_to    = st.date_input("עד תאריך", value=pd.Timestamp("2024-06-01"))
    capital    = st.number_input("הון התחלתי ($)", value=config.INITIAL_CAPITAL,
                                 step=1000, min_value=1000)
    risk_trade = st.number_input("סיכון לעסקה ($)", value=config.RISK_PER_TRADE,
                                 step=50, min_value=50)
    run_btn    = st.button("▶  הרץ בקטסט", type="primary", use_container_width=True)

# ── Run ───────────────────────────────────────────────────────────────────────
if run_btn:
    with st.spinner(f"טוען נתונים ומריץ בקטסט על {symbol}… (עלול לקחת כמה דקות בפעם הראשונה)"):
        try:
            trades, m15, h1 = _cached_backtest(symbol, str(date_from), str(date_to), risk_trade)
            if trades is None:
                st.error("לא מספיק נתוני M15. נסה טווח תאריכים רחב יותר.")
                st.stop()
            stats  = compute_stats(trades, capital)

            st.session_state["bt_trades"] = trades
            st.session_state["bt_stats"]  = stats
            st.session_state["bt_capital"] = capital
            st.session_state["bt_symbol"]  = symbol
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
