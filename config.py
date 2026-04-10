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
SWING_N_LTF = 5   # on 15M

# ── FVG (Fair Value Gap / Imbalance) ─────────────────────────────────────────
FVG_MIN_SIZE  = 0.0002   # minimum gap size in price units (filters micro-gaps)
FVG_PROXIMITY = 0.0010   # max distance from 75% Fib for FVG to be "at" entry
# Set to False to skip FVG check (useful for validating other conditions first)
REQUIRE_FVG   = False

# ── Liquidity sweeps ─────────────────────────────────────────────────────────
LIQ_TOLERANCE = 0.05   # % tolerance for two swing highs/lows to count as "equal"
                       # e.g. 0.05 → within 5 pips on a 1.0000 price

# ── Entry ────────────────────────────────────────────────────────────────────
# Price must come within this buffer of the 75% Fib level to trigger entry
ENTRY_BUFFER = 0.0005

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
