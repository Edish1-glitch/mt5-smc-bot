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
    initial_sidebar_state="expanded",
)

st.title("📊 SMC / ICT Strategy Dashboard")
st.markdown("---")

st.markdown("""
### מה יש כאן?

השתמש בסרגל הצד לנווט בין העמודים:

- **🔬 Backtest** — הרץ בקטסט מלא על סימבול, ראה סטטיסטיקות מלאות + equity curve + פירוט עסקאות
- **🔍 Scan Mode** — סקן סטאפים ידנית עם גרפי TradingView (BOS, Fib, FVG) + כפתורי YES/NO
- **📊 Compare** — הרץ כמה סימבולים במקביל וראה טבלת השוואה

---

### האסטרטגיה

5 תנאים לכניסה לעסקה:
1. **HTF Bias** — BOS על H1 קובע כיוון (bull/bear)
2. **M15 BOS** — BOS על M15 מאשר את הכיוון
3. **Liquidity Sweep** — נזילות נמחקה לפני ה-BOS
4. **Fibonacci 75%** — מחיר חוזר לרמת ה-75% של הפיב
5. **FVG** — Fair Value Gap לא ממוזג ליד רמת הכניסה

---
""")

col1, col2, col3 = st.columns(3)
with col1:
    st.info("**Risk per trade**: $500 (0.5%)")
with col2:
    st.info("**Entry**: 75% Fibonacci")
with col3:
    st.info("**Timeframes**: H1 bias + M15 entry")
