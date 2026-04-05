"""Tests for liquidity sweep detection."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pandas as pd
import numpy as np
import pytest
from strategy.liquidity import find_equal_highs, find_equal_lows, detect_sweeps, liquidity_was_swept
from strategy.swings import get_swing_points


def make_df(highs, lows, closes=None):
    n = len(highs)
    opens = [l + (h - l) * 0.3 for h, l in zip(highs, lows)]
    if closes is None:
        closes = [l + (h - l) * 0.6 for h, l in zip(highs, lows)]
    df = pd.DataFrame({
        "open":  opens,
        "high":  highs,
        "low":   lows,
        "close": closes,
        "volume": [1000] * n,
    })
    df.index = pd.date_range("2024-01-01", periods=n, freq="15min")
    return df


class TestEqualHighs:
    def test_equal_highs_found(self):
        # Two swing highs at nearly the same level (1.0200 and 1.0201)
        highs  = [1.00, 1.01, 1.02, 1.01, 1.00, 1.01, 1.0201, 1.01, 1.00, 1.01, 1.02, 1.01]
        lows   = [h - 0.008 for h in highs]
        df = make_df(highs, lows)
        df = get_swing_points(df, n=2)
        pools = find_equal_highs(df, tolerance_pct=0.1)
        assert len(pools) >= 1

    def test_non_equal_highs_not_found(self):
        # Two swing highs far apart (1.00 and 1.05)
        highs = [0.99, 1.00, 0.99, 0.98, 0.97, 0.98, 1.05, 0.98, 0.97]
        lows  = [h - 0.005 for h in highs]
        df = make_df(highs, lows)
        df = get_swing_points(df, n=2)
        pools = find_equal_highs(df, tolerance_pct=0.1)
        # The two highs are 5% apart, tolerance is 0.1% → no match
        assert pools == []


class TestDetectSweeps:
    def test_bullish_sweep_detected(self):
        """
        Equal lows at ~1.0000.
        Bar sweeps below (low=0.9990) but closes above (close=1.0010).
        """
        # Build: two swing lows at 1.0000, then a sweep candle
        highs  = [1.0050, 1.0020, 1.0050, 1.0020, 1.0050, 1.0020, 1.0050,
                  1.0020, 1.0050, 1.0020, 1.0050, 1.0070, 1.0050, 1.0020, 1.0050]
        lows   = [1.0000, 0.9995, 1.0000, 0.9995, 1.0000, 0.9995, 1.0000,
                  0.9995, 1.0000, 0.9995, 1.0000, 0.9990, 1.0000, 0.9995, 1.0000]
        closes = [1.0040, 1.0010, 1.0040, 1.0010, 1.0040, 1.0010, 1.0040,
                  1.0010, 1.0040, 1.0010, 1.0040, 1.0020, 1.0040, 1.0010, 1.0040]
        df = make_df(highs, lows, closes)
        sweeps = detect_sweeps(df, n_swing=2, tolerance_pct=0.1)
        bull_sweeps = [s for s in sweeps if s["direction"] == "bull"]
        assert len(bull_sweeps) >= 1

    def test_no_sweep_without_rejection(self):
        """Candle pierces below equal lows but closes below too — no sweep."""
        highs  = [1.0050] * 15
        lows   = [1.0000, 0.9995, 1.0000, 0.9995, 1.0000, 0.9995, 1.0000,
                  0.9995, 1.0000, 0.9995, 1.0000, 0.9985, 0.9980, 0.9975, 0.9970]
        closes = [1.0040, 1.0010, 1.0040, 1.0010, 1.0040, 1.0010, 1.0040,
                  1.0010, 1.0040, 1.0010, 0.9990, 0.9983, 0.9977, 0.9971, 0.9965]
        df = make_df(highs, lows, closes)
        sweeps = detect_sweeps(df, n_swing=2, tolerance_pct=0.1)
        bull_sweeps = [s for s in sweeps if s["direction"] == "bull"]
        assert bull_sweeps == []


class TestLiquidityWasSwept:
    def test_swept_before_bar(self):
        sweeps = [{"bar_idx": 10, "direction": "bull", "level": 1.0}]
        assert liquidity_was_swept(sweeps, "bull", before_bar=15) is True

    def test_not_swept_before_bar(self):
        sweeps = [{"bar_idx": 20, "direction": "bull", "level": 1.0}]
        assert liquidity_was_swept(sweeps, "bull", before_bar=15) is False

    def test_wrong_direction_ignored(self):
        sweeps = [{"bar_idx": 5, "direction": "bear", "level": 1.0}]
        assert liquidity_was_swept(sweeps, "bull", before_bar=15) is False
