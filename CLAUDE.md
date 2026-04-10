# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this project is

An SMC/ICT (Smart Money Concepts / Inner Circle Trader) strategy backtester written in Python. It trades forex, gold, indices, and crypto using a 5-condition checklist:
1. HTF (1H) market structure bias via Break of Structure (BOS)
2. M15 BOS confirming LTF direction matches HTF bias
3. Liquidity swept before the BOS
4. Price returning to the 75% Fibonacci retracement level
5. Unmitigated Fair Value Gap (FVG) near the 75% entry

## Running the backtest

```bash
# Quickest — no setup needed (yfinance, ~60 days of M15 data):
python main.py --symbol EURUSD --from 2024-01-01 --to 2024-06-01

# With OANDA (free demo, years of history):
export OANDA_TOKEN=<token>
python main.py --symbol EURUSD --from 2023-01-01 --to 2024-01-01

# Visual review of trades after backtest:
python main.py --symbol EURUSD --from 2024-01-01 --to 2024-06-01 --review

# Manual scan mode (y/n for each setup, opens browser charts):
python main.py --symbol EURUSD --from 2024-01-01 --to 2024-06-01 --scan

# Multiple symbols:
python main.py --symbol EURUSD XAUUSD NAS100 --from 2024-01-01 --to 2024-06-01

# From MT5-exported CSV:
python main.py --symbol EURUSD --csv-m15 eurusd_m15.csv --csv-h1 eurusd_h1.csv \
               --from 2022-01-01 --to 2024-01-01
```

## Running tests

```bash
pytest                          # all tests
pytest tests/test_structure.py  # single file
pytest -v                       # verbose
```

## Data sources and auto-detection

Priority order (auto-detect): `OANDA_TOKEN` set → `MT5_BRIDGE_URL` set → Windows (MT5 direct) → yfinance fallback.

| Source | Env var | Notes |
|--------|---------|-------|
| OANDA | `OANDA_TOKEN` | Best: free demo, years of M15/H1 |
| yfinance | none | No setup; M15 limited to ~60 days |
| MT5 bridge | `MT5_BRIDGE_URL` | Runs `mt5_bridge/server.py` on Windows |
| MT5 direct | — | Windows only |
| Dukascopy | none | Bank-quality, downloads 1-min → resamples; no API key |

Fetched data is cached as Parquet files in `data/cache/`.

## Architecture

```
config.py          — All strategy parameters (swing windows, thresholds, pip sizes)
main.py            — CLI entry point; loads data, dispatches to backtest or scan

strategy/
  swings.py        — Fractal swing high/low detection (strict > / <, no look-ahead)
  structure.py     — BOS detection + HTF bias (uses swings.py)
  fvg.py           — Fair Value Gap detection + mitigation tracking
  liquidity.py     — Equal highs/lows pools + sweep detection
  fibonacci.py     — FibLevels dataclass; entry=75%, SL=100%, TP=0%

backtest/
  engine.py        — Walk-forward bar-by-bar engine; signals recomputed every
                     SWING_N_LTF bars (incremental, O(n²/k) not O(n³))
  trade.py         — Trade dataclass with PnL/R:R calculations
  results.py       — Stats computation (win rate, PF, drawdown, Sharpe) + print

data/
  fetcher.py       — get_ohlcv() with Parquet caching; all source adapters here

review/
  chart.py         — Post-backtest visual review (TradingView Lightweight Charts)
  scanner.py       — Interactive scan mode: finds BOS+Sweep candidates,
                     opens Plotly HTML charts in browser, records y/n decisions

scan_server.py     — Optional Flask server for web-based scanner UI
mt5_bridge/
  server.py        — Flask REST bridge (run on Windows to serve MT5 data to Mac)
```

## Key design decisions

- **No look-ahead bias**: swing detection requires `n` confirmed bars on both sides; the last `n` bars of any DataFrame never get swing labels.
- **BOS full reset**: after every BOS event, all four swing anchor variables are cleared so the next BOS anchors to fresh local swings, not stale ones from months earlier.
- **Incremental FVG mitigation**: FVG mitigation is updated one bar at a time, not re-scanned from scratch each bar. Rebuilt only when the most recent BOS changes.
- **Signal recompute cadence**: BOS/sweep detection re-runs every `SWING_N_LTF` (5) bars; H1 bias re-checks every ~4 M15 bars.
- **Strict fractal definition**: swing high/low uses `>` / `<` (not `>=`) to prevent false positives when adjacent bars share the same value.

## All tunable parameters live in `config.py`

Never hardcode thresholds in strategy modules — put them in `config.py` and import from there.
