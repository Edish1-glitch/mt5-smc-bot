# config.py — Strategy parameters (all tunable here, nothing hardcoded in logic)

# ── Timeframes ──────────────────────────────────────────────────────────────
HTF = "H1"    # 1-hour: directional bias only
LTF = "M15"   # 15-min: entry checklist

# ── Risk ─────────────────────────────────────────────────────────────────────
INITIAL_CAPITAL = 100_000   # USD — used for equity tracking only
RISK_PER_TRADE  = 500       # USD fixed per trade (0.5% static, never changes)

# ── Swing detection ──────────────────────────────────────────────────────────
# Number of bars on each side that must be lower/higher for a valid pivot
SWING_N_HTF = 3   # on 1H
SWING_N_LTF = 3   # on 15M (reduced from 5 for more sensitivity)

# ── FVG (Fair Value Gap / Imbalance) ─────────────────────────────────────────
FVG_MIN_SIZE  = 0.0002   # minimum gap size in price units (filters micro-gaps)
FVG_PROXIMITY = 0.0010   # max distance from 75% Fib for FVG to be "at" entry
# Set to False to skip FVG check (useful for validating other conditions first)
REQUIRE_FVG   = False

# ── Liquidity sweeps ─────────────────────────────────────────────────────────
LIQ_TOLERANCE = 0.05   # % tolerance for two swing highs/lows to count as "equal"
                       # e.g. 0.05 → within 5 pips on a 1.0000 price

# ── Entry ────────────────────────────────────────────────────────────────────
# Price must come within this buffer of the 75% Fib level to trigger entry (default)
ENTRY_BUFFER = 0.0008

# Minimum fib span in price units — filters out micro-swings (default for forex)
MIN_FIB_SPAN = 0.0015

# Per-symbol overrides for ENTRY_BUFFER and MIN_FIB_SPAN
# (instruments with very different price scales need different absolute thresholds)
ENTRY_BUFFER_BY_SYMBOL = {
    "EURUSD": 0.0008,
    "GBPUSD": 0.0008,
    "USDJPY": 0.08,
    "XAUUSD": 0.80,    # Gold ~$2000 → 80c buffer
    "NAS100": 8.0,     # ~$18000 → 8 point buffer
    "US500":  1.0,
    "BTCUSD": 80.0,
}

MIN_FIB_SPAN_BY_SYMBOL = {
    "EURUSD": 0.0015,
    "GBPUSD": 0.0015,
    "USDJPY": 0.15,
    "XAUUSD": 1.50,    # Gold: $1.50 minimum impulse
    "NAS100": 15.0,    # NAS100: 15 points minimum
    "US500":  2.0,
    "BTCUSD": 150.0,
}

def get_entry_buffer(symbol: str) -> float:
    return ENTRY_BUFFER_BY_SYMBOL.get(symbol.upper(), ENTRY_BUFFER)

def get_min_fib_span(symbol: str) -> float:
    return MIN_FIB_SPAN_BY_SYMBOL.get(symbol.upper(), MIN_FIB_SPAN)

# Cooldown: minimum bars between entries on the same BOS setup
ENTRY_COOLDOWN_BARS = 20

# ── Symbols ──────────────────────────────────────────────────────────────────
# Pip sizes per symbol (used for position sizing)
PIP_SIZE = {
    "EURUSD": 0.0001,
    "GBPUSD": 0.0001,
    "USDJPY": 0.01,
    "XAUUSD": 0.01,    # Gold: 1 pip = $0.01
    "NAS100": 0.01,
    "US500":  0.01,
    "BTCUSD": 1.0,
}

# Pip value in USD for a standard lot (100k units)
# These are approximate; real values depend on account currency and broker
PIP_VALUE_PER_LOT = {
    "EURUSD": 10.0,
    "GBPUSD": 10.0,
    "USDJPY": 9.0,
    "XAUUSD": 10.0,
    "NAS100": 10.0,
    "US500":  10.0,
    "BTCUSD": 10.0,
}

SYMBOLS = list(PIP_SIZE.keys())
