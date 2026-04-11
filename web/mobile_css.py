"""
web/mobile_css.py — Mobile-responsive CSS injected into all Streamlit pages.

Call inject_mobile_css() at the top of each page (after st.set_page_config).
"""

import streamlit as st


_MOBILE_CSS = """
<style>
/* === Base typography === */
html, body, [class*="css"] {
  -webkit-tap-highlight-color: rgba(0,0,0,0);
  -webkit-text-size-adjust: 100%;
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

<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
"""


def inject_mobile_css():
    """Inject mobile-responsive CSS + viewport meta tag into the current page."""
    st.markdown(_MOBILE_CSS, unsafe_allow_html=True)
