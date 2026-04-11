"""
web/app.py — SMC Strategy Dashboard (Streamlit)

Run with:
    streamlit run web/app.py
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import streamlit as st

st.set_page_config(
    page_title="SMC Strategy Dashboard",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="collapsed",  # better default for mobile
)

from web.mobile_css import inject_mobile_css, inject_bottom_nav
inject_mobile_css()
inject_bottom_nav("home")

st.title("📊 SMC / ICT Dashboard")

# Mobile-friendly nav cards (HTML <a> tags - no dynamic JS module loading)
st.markdown("### בחר עמוד")
st.markdown("""
<style>
.nav-grid { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 0.5rem; margin-bottom: 1rem; width: 100%; max-width: 100%; }
.nav-card { display: block; text-align: center; padding: 1rem 0.5rem; background: linear-gradient(135deg, #1e2130 0%, #2a2e39 100%); border: 1px solid #2a2e39; border-radius: 12px; text-decoration: none !important; color: #d1d4dc !important; font-size: 0.95rem; font-weight: 600; transition: all 0.15s ease; min-width: 0; }
.nav-card:hover, .nav-card:active { background: linear-gradient(135deg, #00bcd4 0%, #0097a7 100%); color: white !important; transform: translateY(-2px); box-shadow: 0 4px 12px rgba(0,188,212,0.3); }
.nav-card .ico { display: block; font-size: 1.6rem; margin-bottom: 0.25rem; }
@media (max-width: 480px) {
  .nav-card { padding: 0.8rem 0.3rem; font-size: 0.85rem; }
  .nav-card .ico { font-size: 1.4rem; }
}
</style>
<div class="nav-grid">
  <a class="nav-card" href="/Backtest" target="_self"><span class="ico">🔬</span>Backtest</a>
  <a class="nav-card" href="/Scan" target="_self"><span class="ico">🔍</span>Scan</a>
  <a class="nav-card" href="/Compare" target="_self"><span class="ico">📊</span>Compare</a>
</div>
""", unsafe_allow_html=True)

st.markdown("---")

with st.expander("📖 איך זה עובד?", expanded=False):
    st.markdown("""
**העמודים:**
- **🔬 Backtest** — בקטסט מלא: סטטיסטיקות + equity curve + פירוט עסקאות + גרף ויזואלי לכל עסקה
- **🔍 Scan** — סקאן סטאפים עם גרפי TradingView ו-BOS / Fib / FVG מסומנים
- **📊 Compare** — השוואה בין כמה סימבולים במקביל

**האסטרטגיה (5 תנאים):**
1. **HTF Bias** — BOS על H1 קובע כיוון
2. **M15 BOS** — אישור כיוון
3. **Liquidity Sweep** — נזילות נמחקה לפני ה-BOS
4. **Fibonacci 75%** — מחיר חוזר ל-OTE
5. **FVG** *(אופציונלי)* — Fair Value Gap ליד הכניסה
""")

c1, c2, c3 = st.columns(3)
c1.metric("Default Risk", "0.5%", help="$500 על תיק של $100K")
c2.metric("Entry", "Fib 75%", help="OTE — Optimal Trade Entry")
c3.metric("R:R", "1:3", help="3x reward על כל יחידת סיכון")
