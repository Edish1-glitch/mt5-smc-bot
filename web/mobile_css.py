"""
web/mobile_css.py — Mobile-responsive CSS injected into all Streamlit pages.

Call inject_mobile_css() at the top of each page (after st.set_page_config).
"""

import streamlit as st


_MOBILE_CSS = """
<style>
/* === Base === */
html, body {
  -webkit-tap-highlight-color: rgba(0,0,0,0);
  -webkit-text-size-adjust: 100%;
  overflow-x: hidden !important;
  max-width: 100vw !important;
  /* Respect iOS safe areas (notch / home indicator) */
  padding-left: env(safe-area-inset-left, 0) !important;
  padding-right: env(safe-area-inset-right, 0) !important;
}
[class*="css"] { -webkit-tap-highlight-color: rgba(0,0,0,0); }
.stApp { overflow-x: hidden !important; }

/* === Hide Streamlit chrome we don't need === */
[data-testid="stSidebar"],
[data-testid="stSidebarCollapsedControl"],
[data-testid="collapsedControl"],
header[data-testid="stHeader"],
footer,
#MainMenu,
.stDeployButton,
[data-testid="stDecoration"],
[data-testid="stStatusWidget"] {
  display: none !important;
  visibility: hidden !important;
  width: 0 !important;
  height: 0 !important;
}

/* Reclaim full width since sidebar is gone */
[data-testid="stAppViewContainer"] > .main,
.stMain {
  margin-left: 0 !important;
  width: 100% !important;
  max-width: 100% !important;
}
.stMainBlockContainer, .block-container {
  max-width: 760px !important;
  margin: 0 auto !important;
  padding-top: max(1rem, env(safe-area-inset-top)) !important;
  padding-bottom: calc(6rem + env(safe-area-inset-bottom, 0)) !important;
}

/* === Custom bottom navigation bar === */
.smc-bottom-nav {
  position: fixed;
  bottom: 0;
  left: 0;
  right: 0;
  background: linear-gradient(180deg, rgba(19,23,34,0.95) 0%, rgba(19,23,34,1) 100%);
  backdrop-filter: blur(10px);
  -webkit-backdrop-filter: blur(10px);
  border-top: 1px solid #2a2e39;
  display: flex;
  justify-content: space-around;
  align-items: center;
  padding: 0.5rem 0 calc(0.5rem + env(safe-area-inset-bottom)) 0;
  z-index: 9999;
}
.smc-bottom-nav a {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 0.5rem 0.25rem;
  text-decoration: none !important;
  color: #888 !important;
  font-size: 0.7rem;
  font-weight: 600;
  transition: all 0.15s ease;
  min-height: 56px;
}
.smc-bottom-nav a .ico { font-size: 1.4rem; margin-bottom: 0.15rem; line-height: 1; }
.smc-bottom-nav a:hover, .smc-bottom-nav a:active { color: #00bcd4 !important; }
.smc-bottom-nav a.active {
  color: #00bcd4 !important;
  background: rgba(0,188,212,0.08);
  border-radius: 8px;
}

/* === Larger touch targets globally === */
button, .stButton > button {
  min-height: 44px !important;
  font-size: 15px !important;
}

/* === Mobile (<= 768px) === */
@media (max-width: 768px) {
  /* Tighter padding to maximise content */
  .block-container, .stMainBlockContainer {
    padding-top: 1rem !important;
    padding-left: 0.75rem !important;
    padding-right: 0.75rem !important;
    padding-bottom: 1rem !important;
    max-width: 100% !important;
  }

  /* Title smaller on mobile */
  h1 { font-size: 1.5rem !important; line-height: 1.2 !important; }
  h2 { font-size: 1.25rem !important; }
  h3 { font-size: 1.1rem !important; }

  /* Sidebar overlay style on mobile */
  [data-testid="stSidebar"] {
    width: 85vw !important;
    min-width: 280px !important;
  }

  /* Make all buttons full-width on mobile */
  .stButton > button {
    width: 100% !important;
    min-height: 48px !important;
    font-size: 16px !important;
    font-weight: 600 !important;
  }

  /* Inputs bigger and easier to tap */
  input, select, textarea {
    font-size: 16px !important;  /* prevents iOS zoom-in on focus */
    min-height: 44px !important;
  }

  /* Number input +/- buttons larger */
  [data-testid="stNumberInput"] button {
    min-width: 44px !important;
    min-height: 44px !important;
  }

  /* Date input larger */
  [data-testid="stDateInput"] input {
    font-size: 16px !important;
    min-height: 44px !important;
  }

  /* Metric cards stack better */
  [data-testid="stMetric"] {
    padding: 0.5rem !important;
  }
  [data-testid="stMetricLabel"] { font-size: 0.75rem !important; }
  [data-testid="stMetricValue"] { font-size: 1.3rem !important; }

  /* Force columns to stack vertically on mobile (prevents tiny squished metrics) */
  [data-testid="stHorizontalBlock"] {
    flex-wrap: wrap !important;
    gap: 0.5rem !important;
  }
  [data-testid="stHorizontalBlock"] > [data-testid="stColumn"] {
    flex: 1 1 calc(50% - 0.5rem) !important;
    min-width: calc(50% - 0.5rem) !important;
  }

  /* DataFrames scroll horizontally instead of squishing */
  [data-testid="stDataFrame"] {
    overflow-x: auto !important;
  }

  /* TradingView chart iframe height adjusted for mobile */
  iframe {
    max-width: 100% !important;
  }

  /* Hide Streamlit footer + header on mobile to maximise screen */
  header[data-testid="stHeader"] {
    height: 2.5rem !important;
  }
  footer { display: none !important; }

  /* RTL alignment helper for Hebrew labels */
  [data-testid="stSidebar"] .stMarkdown,
  [data-testid="stSidebar"] label {
    direction: rtl;
  }
}

/* === Tablet (768px - 1024px) === */
@media (min-width: 769px) and (max-width: 1024px) {
  .block-container, .stMainBlockContainer {
    padding: 1rem !important;
    max-width: 100% !important;
  }
  [data-testid="stHorizontalBlock"] > [data-testid="stColumn"] {
    flex: 1 1 calc(33% - 0.5rem) !important;
  }
}

/* === Always-on niceties === */
/* Smoother scrolling */
html { scroll-behavior: smooth; }

/* Better focus rings */
button:focus-visible, input:focus-visible {
  outline: 2px solid #00bcd4 !important;
  outline-offset: 2px !important;
}

/* Better contrast for primary buttons */
.stButton > button[kind="primary"] {
  background: linear-gradient(135deg, #00bcd4 0%, #0097a7 100%) !important;
  color: white !important;
  border: none !important;
}
.stButton > button[kind="primary"]:hover {
  background: linear-gradient(135deg, #00acc1 0%, #00838f 100%) !important;
  transform: translateY(-1px);
  box-shadow: 0 4px 8px rgba(0,188,212,0.3);
}
</style>

<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no, viewport-fit=cover">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="theme-color" content="#131722">
"""


def inject_mobile_css():
    """Inject mobile-responsive CSS + viewport meta tag into the current page."""
    st.markdown(_MOBILE_CSS, unsafe_allow_html=True)


def inject_bottom_nav(active: str = ""):
    """
    Inject the fixed bottom navigation bar.
    `active` should be one of: "home", "backtest", "scan", "compare"
    """
    def cls(name: str) -> str:
        return "active" if name == active else ""

    nav_html = f"""
<div class="smc-bottom-nav">
  <a href="/" target="_self" class="{cls('home')}"><span class="ico">🏠</span>בית</a>
  <a href="/Backtest" target="_self" class="{cls('backtest')}"><span class="ico">🔬</span>בקטסט</a>
  <a href="/Scan" target="_self" class="{cls('scan')}"><span class="ico">🔍</span>סקאן</a>
  <a href="/Compare" target="_self" class="{cls('compare')}"><span class="ico">📊</span>השוואה</a>
</div>
"""
    st.markdown(nav_html, unsafe_allow_html=True)
