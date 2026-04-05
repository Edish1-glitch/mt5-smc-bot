"""
mt5_bridge/server.py — MT5 REST Bridge Server
==============================================

רץ על Windows עם MT5 מותקן.
מאפשר ל-Mac/Linux לשלוף נתוני OHLCV ולהריץ באקטסטים מרחוק.

התקנה (Windows):
    pip install flask MetaTrader5 pandas pyarrow

הפעלה:
    python mt5_bridge/server.py

    # עם IP/port מותאם אישית:
    python mt5_bridge/server.py --host 0.0.0.0 --port 5000

    # עם אימות (מומלץ אם חשוף לאינטרנט):
    python mt5_bridge/server.py --token MY_SECRET_TOKEN

חיבור מ-Mac:
    export MT5_BRIDGE_URL=http://<Windows-IP>:5000
    export MT5_BRIDGE_TOKEN=MY_SECRET_TOKEN   # אם הוגדר
    python main.py --symbol EURUSD --from 2023-01-01 --to 2024-01-01 --source bridge

Endpoints:
    GET /ping                            — בדיקת חיבור
    GET /symbols                         — רשימת סמלים זמינים ב-MT5
    GET /ohlcv?symbol=EURUSD&tf=M15
             &from=2023-01-01&to=2024-01-01  — הורדת נתוני OHLCV
"""

import argparse
import sys
from datetime import datetime, timezone

import pandas as pd

try:
    from flask import Flask, request, jsonify
except ImportError:
    print("ERROR: Flask not installed. Run: pip install flask")
    sys.exit(1)

try:
    import MetaTrader5 as mt5
except ImportError:
    print("ERROR: MetaTrader5 not installed (requires Windows). Run: pip install MetaTrader5")
    sys.exit(1)

app = Flask(__name__)

# Optional bearer token for basic auth
_TOKEN: str = ""

_MT5_TF = {
    "M1":  mt5.TIMEFRAME_M1,
    "M5":  mt5.TIMEFRAME_M5,
    "M15": mt5.TIMEFRAME_M15,
    "M30": mt5.TIMEFRAME_M30,
    "H1":  mt5.TIMEFRAME_H1,
    "H4":  mt5.TIMEFRAME_H4,
    "D1":  mt5.TIMEFRAME_D1,
}


def _check_auth():
    if not _TOKEN:
        return None  # no auth configured
    auth = request.headers.get("Authorization", "")
    if auth != f"Bearer {_TOKEN}":
        return jsonify({"error": "Unauthorized"}), 401
    return None


def _ensure_mt5():
    if not mt5.terminal_info():
        if not mt5.initialize():
            return False, mt5.last_error()
    return True, None


# ── Endpoints ────────────────────────────────────────────────────────────────

@app.get("/ping")
def ping():
    ok, err = _ensure_mt5()
    if not ok:
        return jsonify({"status": "error", "mt5_error": str(err)}), 500
    info = mt5.terminal_info()
    return jsonify({
        "status": "ok",
        "mt5_build": info.build,
        "mt5_connected": info.connected,
    })


@app.get("/symbols")
def symbols():
    denied = _check_auth()
    if denied:
        return denied
    ok, err = _ensure_mt5()
    if not ok:
        return jsonify({"error": str(err)}), 500

    syms = mt5.symbols_get()
    names = sorted(s.name for s in syms) if syms else []
    return jsonify({"symbols": names, "count": len(names)})


@app.get("/ohlcv")
def ohlcv():
    denied = _check_auth()
    if denied:
        return denied

    symbol   = request.args.get("symbol", "").upper()
    tf_str   = request.args.get("tf", "M15").upper()
    date_from = request.args.get("from")
    date_to   = request.args.get("to")

    if not all([symbol, date_from, date_to]):
        return jsonify({"error": "Missing params: symbol, tf, from, to"}), 400

    tf_const = _MT5_TF.get(tf_str)
    if tf_const is None:
        return jsonify({"error": f"Unknown timeframe: {tf_str}"}), 400

    ok, err = _ensure_mt5()
    if not ok:
        return jsonify({"error": f"MT5 init failed: {err}"}), 500

    try:
        dt_from = datetime.fromisoformat(date_from).replace(tzinfo=timezone.utc)
        dt_to   = datetime.fromisoformat(date_to).replace(tzinfo=timezone.utc)
    except ValueError as e:
        return jsonify({"error": f"Bad date format: {e}"}), 400

    rates = mt5.copy_rates_range(symbol, tf_const, dt_from, dt_to)

    if rates is None or len(rates) == 0:
        return jsonify({"error": f"No data for {symbol} {tf_str}", "mt5_error": str(mt5.last_error())}), 404

    df = pd.DataFrame(rates)
    df["time"] = pd.to_datetime(df["time"], unit="s", utc=True).dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    df = df.rename(columns={"tick_volume": "volume"})
    records = df[["time", "open", "high", "low", "close", "volume"]].to_dict("records")

    return jsonify(records)


# ── Main ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="MT5 REST Bridge Server")
    parser.add_argument("--host",  default="0.0.0.0", help="Host to bind (default: 0.0.0.0)")
    parser.add_argument("--port",  type=int, default=5000, help="Port (default: 5000)")
    parser.add_argument("--token", default="", help="Optional Bearer token for auth")
    args = parser.parse_args()

    _TOKEN = args.token

    print("=" * 55)
    print("  MT5 REST Bridge Server")
    print("=" * 55)
    print(f"  URL:   http://{args.host}:{args.port}")
    print(f"  Auth:  {'enabled (Bearer token)' if _TOKEN else 'disabled (local only)'}")
    print()

    # Init MT5 on startup to verify it's running
    if not mt5.initialize():
        print(f"  WARNING: MT5 initialize() failed: {mt5.last_error()}")
        print("  Make sure MetaTrader5 is running and logged in.")
    else:
        info = mt5.terminal_info()
        print(f"  MT5 build:     {info.build}")
        print(f"  MT5 connected: {info.connected}")
        acct = mt5.account_info()
        if acct:
            print(f"  Account:       #{acct.login}  {acct.server}  ({acct.currency})")
        print()

    print(f"  Endpoints:")
    print(f"    GET /ping")
    print(f"    GET /symbols")
    print(f"    GET /ohlcv?symbol=EURUSD&tf=M15&from=2023-01-01&to=2024-01-01")
    print()
    print("  From Mac/Linux set env and run:")
    print(f"    export MT5_BRIDGE_URL=http://<your-windows-ip>:{args.port}")
    if _TOKEN:
        print(f"    export MT5_BRIDGE_TOKEN={_TOKEN}")
    print(f"    python main.py --symbol EURUSD --from 2023-01-01 --to 2024-01-01")
    print("=" * 55)

    app.run(host=args.host, port=args.port, debug=False)
