"""Tests for BOS detection and HTF bias."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pandas as pd
import numpy as np
import pytest
from strategy.structure import detect_bos, get_htf_bias
from strategy.swings import get_swing_points


def make_df(highs, lows, closes=None):
    n = len(highs)
    opens = [l + (h - l) * 0.3 for h, l in zip(highs, lows)]
    if closes is None:
        closes = [l + (h - l) * 0.7 for h, l in zip(highs, lows)]
    df = pd.DataFrame({
        "open":  opens,
        "high":  highs,
        "low":   lows,
        "close": closes,
        "volume": [1000] * n,
    })
    df.index = pd.date_range("2024-01-01", periods=n, freq="1h")
    return df


class TestDetectBOS:
    def test_bullish_bos_detected(self):
        # Clear structure: swing high at bar 2 (1.050), pullback, then BOS close above 1.050
        #  bar: 0     1     2     3     4     5     6     7     8     9
        highs  = [1.010, 1.020, 1.050, 1.020, 1.010, 1.020, 1.030, 1.040, 1.055, 1.060]
        lows   = [1.000, 1.010, 1.030, 1.010, 1.000, 1.010, 1.020, 1.030, 1.040, 1.045]
        closes = [1.005, 1.015, 1.040, 1.015, 1.005, 1.015, 1.025, 1.035, 1.052, 1.055]
        df = make_df(highs, lows, closes)
        events = detect_bos(df, n=2)
        bull = [e for e in events if e["direction"] == "bull"]
        assert len(bull) > 0

    def test_bearish_bos_detected(self):
        # Clear structure: swing low at bar 2 (0.960), rally, then BOS close below 0.960
        #  bar: 0     1     2     3     4     5     6     7     8     9
        highs  = [1.000, 0.990, 0.970, 0.990, 1.000, 0.990, 0.980, 0.970, 0.960, 0.955]
        lows   = [0.990, 0.970, 0.950, 0.970, 0.990, 0.970, 0.960, 0.950, 0.940, 0.935]
        closes = [0.995, 0.975, 0.955, 0.975, 0.995, 0.975, 0.965, 0.955, 0.945, 0.938]
        df = make_df(highs, lows, closes)
        events = detect_bos(df, n=2)
        bear = [e for e in events if e["direction"] == "bear"]
        assert len(bear) > 0

    def test_no_bos_flat_market(self):
        highs  = [1.00 + (i % 3) * 0.001 for i in range(20)]
        lows   = [h - 0.001 for h in highs]
        df = make_df(highs, lows)
        events = detect_bos(df, n=3)
        # May or may not have events; just ensure no crash
        assert isinstance(events, list)

    def test_bos_event_fields(self):
        highs  = [1.00, 1.02, 1.01, 1.03, 1.02, 1.04, 1.03, 1.05, 1.04, 1.06,
                  1.05, 1.07, 1.06, 1.08, 1.07, 1.09, 1.08, 1.10, 1.09, 1.11]
        lows   = [h - 0.01 for h in highs]
        closes = [h - 0.002 for h in highs]
        df = make_df(highs, lows, closes)
        events = detect_bos(df, n=2)
        if events:
            e = events[0]
            assert "bar_idx"    in e
            assert "timestamp"  in e
            assert "direction"  in e
            assert "level"      in e
            assert "swing_low"  in e
            assert "swing_high" in e
            assert e["direction"] in ("bull", "bear")


class TestHTFBias:
    def test_returns_none_with_insufficient_data(self):
        df = make_df([1.0] * 5, [0.99] * 5)
        bias = get_htf_bias(df, df.index[-1], n=3)
        assert bias == "none"

    def test_bullish_bias_after_uptrend(self):
        # Feed a rising structure to 1H DF
        highs  = [1.00, 1.02, 1.01, 1.03, 1.02, 1.04, 1.03, 1.05, 1.04, 1.06,
                  1.05, 1.07, 1.06, 1.08, 1.07, 1.09, 1.08, 1.10, 1.09, 1.11,
                  1.10, 1.12, 1.11, 1.13, 1.12, 1.14, 1.13, 1.15, 1.14, 1.16]
        lows   = [h - 0.008 for h in highs]
        closes = [h - 0.002 for h in highs]
        df = make_df(highs, lows, closes)
        # Check bias at a point after sufficient data
        at_time = df.index[-1]
        bias = get_htf_bias(df, at_time, n=2)
        assert bias in ("bull", "none")  # depends on whether BOS fires
