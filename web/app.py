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

from web.mobile_css import inject_mobile_css
inject_mobile_css()

st.title("📊 SMC / ICT Dashboard")

# Mobile-friendly nav cards
st.markdown("### בחר עמוד")
nav_c1, nav_c2, nav_c3 = st.columns(3)
with nav_c1:
    st.page_link("pages/1_Backtest.py", label="🔬 Backtest", use_container_width=True)
with nav_c2:
    st.page_link("pages/2_Scan.py", label="🔍 Scan", use_container_width=True)
with nav_c3:
    st.page_link("pages/3_Compare.py", label="📊 Compare", use_container_width=True)

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
