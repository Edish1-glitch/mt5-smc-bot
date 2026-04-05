"""
validate_strategy.py — הדגמה ויזואלית (טקסט) של לוגיקת הזיהוי

מריץ את כל הדטקטורים על נתונים סינתטיים שמייצגים סטאפ אמיתי:
  1. 1H bias — מבנה עולה ברור
  2. 15M Liquidity Sweep — ניקוי stops
  3. 15M BOS עם Imbalance (FVG)
  4. Fibonacci 75% — רמת כניסה
  5. FVG ליד ה-75%

כיצד לאמת על נתונים אמיתיים:
  python mt5_bot/main.py --symbol EURUSD --from 2024-01-01 --to 2024-06-01
  (על Windows עם MT5 מותקן)
"""

import sys, os
sys.path.insert(0, os.path.dirname(__file__))

import pandas as pd
import numpy as np

from strategy.swings    import get_swing_points
from strategy.structure import detect_bos, get_htf_bias
from strategy.fvg       import detect_fvg, update_mitigation, fvg_near_price
from strategy.liquidity import detect_sweeps, liquidity_was_swept
from strategy.fibonacci import calculate_fib_levels, price_at_entry_zone
import config

SEP = "─" * 60


def make_df(rows, freq, start="2024-06-10 00:00"):
    df = pd.DataFrame(rows, columns=["open", "high", "low", "close", "volume"])
    df.index = pd.date_range(start, periods=len(df), freq=freq)
    return df


# ─────────────────────────────────────────────────────────────
# H1 data — מבנה עולה ברור לקבלת bias = 'bull'
#
# עם n=3 הלולאה בודקת בר i אם high[i] == max(high[i-3:i+4])
# → בר 3 (high=1.0900) יהיה swing high כי הנרות סביבו נמוכים יותר
# → בר 8 (close=1.0902) יסגור מעל ה-1.0900 → BOS = bull
# ─────────────────────────────────────────────────────────────
H1_ROWS = [
    # open     high     low      close    vol
    (1.0820,  1.0832,  1.0810,  1.0825,  1000),  # 0
    (1.0825,  1.0850,  1.0820,  1.0845,  1000),  # 1
    (1.0845,  1.0870,  1.0840,  1.0865,  1000),  # 2
    (1.0865,  1.0900,  1.0860,  1.0895,  1000),  # 3  ← swing high candidate (1.0900)
    (1.0895,  1.0875,  1.0848,  1.0855,  1000),  # 4  ← pullback
    (1.0855,  1.0845,  1.0820,  1.0828,  1000),  # 5  ← swing low (1.0820)
    (1.0828,  1.0858,  1.0822,  1.0852,  1000),  # 6
    (1.0852,  1.0880,  1.0845,  1.0875,  1000),  # 7
    (1.0875,  1.0908,  1.0868,  1.0902,  1000),  # 8  ← BOS: close 1.0902 > swing_high 1.0900
    (1.0902,  1.0925,  1.0895,  1.0920,  1000),  # 9
    (1.0920,  1.0940,  1.0912,  1.0935,  1000),  # 10
]

# ─────────────────────────────────────────────────────────────
# M15 data — סטאפ מלא
#
# עם n=5:
# Phase 1 (bars 0-12):  שני swing lows שווים ~1.0840 ← liquidity pool
# Phase 2 (bar 13):     SWEEP: low=1.0832 (<1.0840), close=1.0848 (>1.0840)
# Phase 3 (bars 14-20): impulse bullish + FVG בנרות 16-18
#                        FVG: low[18]=1.0902 > high[16]=1.0890 → gap [1.0890–1.0902]
# Phase 4 (bar 20):     BOS: close=1.0945 > prev swing high
# Phase 5 (bars 21-28): pullback ל-75% Fib
#                        impulse_low=1.0840 (100%), impulse_high=1.0945 (0%)
#                        75% = 1.0945 - 0.75*(1.0945-1.0840) = 1.0945-0.0079 = 1.0866
#                        FVG [1.0890–1.0902] קרוב ל-75%=1.0866 (gap_proximity*10)
# ─────────────────────────────────────────────────────────────
M15_ROWS = [
    # open     high     low      close    vol
    (1.0880,  1.0895,  1.0870,  1.0885,  1000),  # 0
    (1.0885,  1.0892,  1.0865,  1.0870,  1000),  # 1
    (1.0870,  1.0878,  1.0848,  1.0855,  1000),  # 2
    (1.0855,  1.0868,  1.0840,  1.0845,  1000),  # 3  ← swing low #1 (1.0840)
    (1.0845,  1.0862,  1.0842,  1.0858,  1000),  # 4
    (1.0858,  1.0875,  1.0852,  1.0870,  1000),  # 5  ← swing high candidate
    (1.0870,  1.0882,  1.0860,  1.0875,  1000),  # 6
    (1.0875,  1.0885,  1.0858,  1.0865,  1000),  # 7
    (1.0865,  1.0872,  1.0845,  1.0850,  1000),  # 8
    (1.0850,  1.0862,  1.0840,  1.0845,  1000),  # 9  ← swing low #2 (1.0840) — equal lows!
    (1.0845,  1.0858,  1.0842,  1.0852,  1000),  # 10
    (1.0852,  1.0860,  1.0845,  1.0855,  1000),  # 11
    (1.0855,  1.0862,  1.0848,  1.0858,  1000),  # 12
    (1.0858,  1.0870,  1.0832,  1.0848,  1000),  # 13 ← SWEEP: low<1.0840, close>1.0840 ✓
    (1.0848,  1.0862,  1.0842,  1.0858,  1000),  # 14
    (1.0858,  1.0878,  1.0852,  1.0875,  1000),  # 15
    (1.0875,  1.0890,  1.0868,  1.0885,  1000),  # 16 ← BEFORE FVG: high=1.0890
    (1.0885,  1.0930,  1.0882,  1.0925,  1000),  # 17 ← IMPULSE נר
    (1.0925,  1.0945,  1.0902,  1.0940,  1000),  # 18 ← AFTER FVG: low=1.0902 > high[16]=1.0890 → FVG!
    (1.0940,  1.0952,  1.0935,  1.0948,  1000),  # 19
    (1.0948,  1.0960,  1.0942,  1.0955,  1000),  # 20 ← BOS: close=1.0955 > swing high
    (1.0955,  1.0962,  1.0945,  1.0950,  1000),  # 21 ← pullback מתחיל
    (1.0950,  1.0955,  1.0932,  1.0938,  1000),  # 22
    (1.0938,  1.0945,  1.0920,  1.0925,  1000),  # 23
    (1.0925,  1.0932,  1.0905,  1.0910,  1000),  # 24
    (1.0910,  1.0918,  1.0888,  1.0892,  1000),  # 25 ← נכנס לאזור ה-FVG [1.0890–1.0902]
    (1.0892,  1.0900,  1.0862,  1.0868,  1000),  # 26 ← מגיע ל-75% Fib ~1.0866 ← ENTRY ✓
    (1.0868,  1.0888,  1.0860,  1.0882,  1000),  # 27
    (1.0882,  1.0910,  1.0875,  1.0905,  1000),  # 28
    (1.0905,  1.0935,  1.0898,  1.0930,  1000),  # 29
    (1.0930,  1.0955,  1.0922,  1.0952,  1000),  # 30 ← מתקרב ל-TP
]


def run_validation():
    # H1 starts at 00:00 → BOS fires at bar 8 = 08:00
    # M15 starts at 09:00 → setup occurs well after H1 BOS ✓
    h1_df  = make_df(H1_ROWS,  freq="1h",    start="2024-06-10 00:00")
    m15_df = make_df(M15_ROWS, freq="15min", start="2024-06-10 09:00")

    print(f"\n{'═'*60}")
    print("  SMC/ICT Strategy — אימות לוגיקה שלב אחר שלב")
    print(f"{'═'*60}")
    print(f"  נכס:       EURUSD (נתונים סינתטיים, לוגיקה אמיתית)")
    print(f"  SWING_N:   HTF={config.SWING_N_HTF}, LTF={config.SWING_N_LTF}")
    print(f"  FVG_PROX:  {config.FVG_PROXIMITY}")
    print(f"  LIQ_TOL:   {config.LIQ_TOLERANCE}%")

    # ── שלב 1: HTF Bias ──────────────────────────────────────
    print(f"\n{SEP}")
    print("  שלב 1 › הטיה על 1H (HTF Bias)")
    print(SEP)

    df_h1_sw = get_swing_points(h1_df, n=config.SWING_N_HTF)
    sh = df_h1_sw[df_h1_sw["swing_high"]]
    sl = df_h1_sw[df_h1_sw["swing_low"]]
    print(f"  Swing highs זוהו: {len(sh)}")
    for ts, row in sh.iterrows():
        print(f"    SH @ {ts}  high={row['high']:.4f}")
    print(f"  Swing lows זוהו:  {len(sl)}")
    for ts, row in sl.iterrows():
        print(f"    SL @ {ts}  low={row['low']:.4f}")

    bos_h1 = detect_bos(h1_df, n=config.SWING_N_HTF)
    print(f"\n  BOS events על 1H: {len(bos_h1)}")
    for e in bos_h1:
        print(f"    [{e['direction'].upper()}] @ {e['timestamp']}  "
              f"level={e['level']:.4f}  impulse=[{e['swing_low']:.4f}–{e['swing_high']:.4f}]")

    # בדיקת bias ב-M15 bar 26 (זמן כניסה משוער) —
    # חייב להיות אחרי שה-H1 BOS כבר קרה
    at_time = m15_df.index[26]
    bias = get_htf_bias(h1_df, at_time, n=config.SWING_N_HTF)
    color = "🟢" if bias == "bull" else ("🔴" if bias == "bear" else "⚪")
    print(f"\n  {color} bias = '{bias}' {'→ LONG בלבד' if bias=='bull' else '→ SHORT בלבד' if bias=='bear' else '→ אין עסקה'}")

    if bias == "none":
        print("  ❌ אין bias — מוסיפים יותר נרות ל-H1")
        return

    # ── שלב 2: Liquidity Sweep ───────────────────────────────
    print(f"\n{SEP}")
    print("  שלב 2 › Liquidity Sweep — ניקוי stops (15M)")
    print(SEP)

    df_m15_sw = get_swing_points(m15_df, n=config.SWING_N_LTF)
    sh15 = df_m15_sw[df_m15_sw["swing_high"]]
    sl15 = df_m15_sw[df_m15_sw["swing_low"]]
    print(f"  Swing highs (15M): {len(sh15)}")
    print(f"  Swing lows  (15M): {len(sl15)}")
    for ts, row in sl15.iterrows():
        print(f"    SL @ bar {m15_df.index.get_loc(ts)}  {ts}  low={row['low']:.4f}")

    sweeps = detect_sweeps(m15_df, n_swing=config.SWING_N_LTF)
    print(f"\n  Sweep events: {len(sweeps)}")
    for s in sweeps:
        label = "🔵 BULL sweep (sell-stops נוקו → setup long)" if s["direction"] == "bull" \
                else "🔴 BEAR sweep (buy-stops נוקו → setup short)"
        print(f"    {label}  @ bar {s['bar_idx']} {s['timestamp']}  level={s['level']:.4f}")

    # ── שלב 3: BOS 15M ───────────────────────────────────────
    print(f"\n{SEP}")
    print("  שלב 3 › BOS על 15M — שבירת מבנה")
    print(SEP)

    bos_m15 = detect_bos(m15_df, n=config.SWING_N_LTF)
    print(f"  BOS events: {len(bos_m15)}")
    for e in bos_m15:
        print(f"    [{e['direction'].upper()}] @ bar {e['bar_idx']} {e['timestamp']}  "
              f"level={e['level']:.4f}  impulse=[{e['swing_low']:.4f}–{e['swing_high']:.4f}]")

    matching = [e for e in bos_m15 if e["direction"] == bias]
    if not matching:
        print(f"\n  ❌ אין BOS שתואם ל-bias='{bias}'")
        return

    last_bos = matching[-1]
    print(f"\n  ✅ BOS נבחר: bar {last_bos['bar_idx']} @ {last_bos['timestamp']}")
    print(f"     impulse_low  (100%/SL) = {last_bos['swing_low']:.4f}")
    print(f"     impulse_high (0%/TP)   = {last_bos['swing_high']:.4f}")

    liq_swept = liquidity_was_swept(sweeps, bias, last_bos["bar_idx"])
    print(f"     נזילות נוקתה לפני BOS: {'✅ כן' if liq_swept else '❌ לא'}")

    # ── שלב 4: Fibonacci ─────────────────────────────────────
    print(f"\n{SEP}")
    print("  שלב 4 › פיבונאצ'י — חישוב רמות")
    print(SEP)

    fib = calculate_fib_levels(
        direction    = last_bos["direction"],
        impulse_low  = last_bos["swing_low"],
        impulse_high = last_bos["swing_high"],
    )
    print(f"  0%   (TP):    {fib.tp:.4f}")
    print(f"  75%  (Entry): {fib.entry:.4f}  ← כניסה")
    print(f"  100% (SL):    {fib.sl:.4f}")
    print(f"  R:R = {fib.risk_reward:.1f}:1  |  span={fib.impulse_high-fib.impulse_low:.4f}")

    entry_bar = None
    for i in range(last_bos["bar_idx"] + 1, len(m15_df)):
        bar = m15_df.iloc[i]
        if price_at_entry_zone(bar["low"],   fib, config.ENTRY_BUFFER) or \
           price_at_entry_zone(bar["close"], fib, config.ENTRY_BUFFER):
            entry_bar = i
            break

    if entry_bar is not None:
        bar = m15_df.iloc[entry_bar]
        print(f"\n  ✅ מחיר הגיע ל-75% @ bar {entry_bar} ({m15_df.index[entry_bar]})")
        print(f"     נר: O={bar['open']:.4f}  H={bar['high']:.4f}  L={bar['low']:.4f}  C={bar['close']:.4f}")
    else:
        print(f"\n  ⏳ מחיר טרם הגיע ל-75% ({fib.entry:.4f})")

    # ── שלב 5: FVG ───────────────────────────────────────────
    print(f"\n{SEP}")
    print("  שלב 5 › FVG — אימבלנס ליד רמת הכניסה")
    print(SEP)

    fvg_list = detect_fvg(m15_df, min_size=config.FVG_MIN_SIZE)
    check_until = entry_bar if entry_bar else len(m15_df)
    for j in range(check_until):
        c = m15_df.iloc[j]
        update_mitigation(fvg_list, c["high"], c["low"])

    print(f"  FVGs שנמצאו: {len(fvg_list)}")
    for f in fvg_list:
        status = "✅ פעיל" if not f["mitigated"] else "❌ mitigated"
        print(f"    [{f['direction'].upper()}] bar {f['bar_idx']}  "
              f"zone=[{f['bottom']:.4f}–{f['top']:.4f}]  {status}")

    fvg_ok = fvg_near_price(fvg_list, fib.entry, config.FVG_PROXIMITY * 10, bias)
    print(f"\n  FVG קרוב לכניסה {fib.entry:.4f}: {'✅ כן' if fvg_ok else '❌ לא (הרחב FVG_PROXIMITY)'}")

    # ── סיכום ────────────────────────────────────────────────
    print(f"\n{'═'*60}")
    all_ok = bias != "none" and bool(matching) and liq_swept \
             and entry_bar is not None and fvg_ok

    if all_ok:
        from backtest.engine import calculate_lot_size
        lot = calculate_lot_size(config.RISK_PER_TRADE, fib.sl_distance, "EURUSD")
        print(f"  ✅  SETUP VALID — עסקה תקפה")
        print(f"{'═'*60}")
        print(f"  כיוון:        {'LONG (קנייה)' if bias == 'bull' else 'SHORT (מכירה)'}")
        print(f"  כניסה:        {fib.entry:.4f}  (75% Fib)")
        print(f"  סטופ לוס:     {fib.sl:.4f}  (100% — swing point)")
        print(f"  טייק פרופיט:  {fib.tp:.4f}  (0%  — origin of move)")
        print(f"  R:R:          {fib.risk_reward:.1f}:1")
        print(f"  סיכון:        ${config.RISK_PER_TRADE}")
        print(f"  גודל פוזיציה: {lot} lots")
    else:
        print(f"  ❌  SETUP INVALID")
        for name, ok in [
            ("1. 1H bias מוגדר",       bias != "none"),
            ("2. BOS תואם bias (15M)",  bool(matching)),
            ("3. נזילות נוקתה",         liq_swept),
            ("4. מחיר ב-75% Fib",      entry_bar is not None),
            ("5. FVG ליד הכניסה",      fvg_ok),
        ]:
            print(f"  {'✅' if ok else '❌'} {name}")
    print()


if __name__ == "__main__":
    run_validation()
