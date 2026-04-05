"""Tests for Fair Value Gap detection."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pandas as pd
import numpy as np
import pytest
from strategy.fvg import detect_fvg, update_mitigation, fvg_near_price


def make_df(rows):
    """rows = list of (open, high, low, close)"""
    df = pd.DataFrame(rows, columns=["open", "high", "low", "close"])
    df["volume"] = 1000
    df.index = pd.date_range("2024-01-01", periods=len(df), freq="15min")
    return df


class TestDetectFVG:
    def test_bullish_fvg_detected(self):
        # candle[0].high=1.0010, candle[2].low=1.0020 → gap 0.0010
        df = make_df([
            (1.0000, 1.0010, 0.9990, 1.0005),  # 0
            (1.0005, 1.0050, 1.0000, 1.0045),  # 1 — impulse candle
            (1.0045, 1.0060, 1.0020, 1.0055),  # 2
        ])
        fvgs = detect_fvg(df, min_size=0.0001)
        bull_fvgs = [f for f in fvgs if f["direction"] == "bull"]
        assert len(bull_fvgs) == 1
        assert bull_fvgs[0]["bottom"] == pytest.approx(1.0010)
        assert bull_fvgs[0]["top"]    == pytest.approx(1.0020)

    def test_bearish_fvg_detected(self):
        # candle[0].low=0.9990, candle[2].high=0.9980 → gap below 0.9990
        df = make_df([
            (1.0010, 1.0015, 0.9990, 0.9995),  # 0
            (0.9995, 0.9998, 0.9940, 0.9945),  # 1 — impulse candle
            (0.9945, 0.9980, 0.9930, 0.9935),  # 2
        ])
        fvgs = detect_fvg(df, min_size=0.0001)
        bear_fvgs = [f for f in fvgs if f["direction"] == "bear"]
        assert len(bear_fvgs) == 1
        assert bear_fvgs[0]["top"]    == pytest.approx(0.9990)
        assert bear_fvgs[0]["bottom"] == pytest.approx(0.9980)

    def test_no_fvg_when_gap_too_small(self):
        df = make_df([
            (1.0000, 1.0010, 0.9990, 1.0005),
            (1.0005, 1.0050, 1.0000, 1.0045),
            (1.0045, 1.0060, 1.0011, 1.0055),  # gap = 0.0001 only
        ])
        fvgs = detect_fvg(df, min_size=0.0005)  # require larger gap
        assert fvgs == []

    def test_no_fvg_when_candles_overlap(self):
        df = make_df([
            (1.0000, 1.0020, 0.9990, 1.0010),
            (1.0010, 1.0060, 0.9980, 1.0050),
            (1.0050, 1.0070, 1.0015, 1.0065),  # low[2]=1.0015 < high[0]=1.0020 → overlap
        ])
        fvgs = detect_fvg(df, min_size=0.0001)
        bull_fvgs = [f for f in fvgs if f["direction"] == "bull"]
        assert bull_fvgs == []


class TestMitigation:
    def test_bullish_fvg_mitigated_when_price_enters_zone(self):
        fvgs = [{"direction": "bull", "top": 1.0020, "bottom": 1.0010, "mitigated": False}]
        update_mitigation(fvgs, candle_high=1.0025, candle_low=1.0015)
        assert fvgs[0]["mitigated"] is True

    def test_bullish_fvg_not_mitigated_above_zone(self):
        fvgs = [{"direction": "bull", "top": 1.0020, "bottom": 1.0010, "mitigated": False}]
        update_mitigation(fvgs, candle_high=1.0080, candle_low=1.0025)
        assert fvgs[0]["mitigated"] is False


class TestFVGNearPrice:
    def test_fvg_near_price_true(self):
        fvgs = [{"direction": "bull", "top": 1.0020, "bottom": 1.0010, "mitigated": False}]
        # zone_mid = 1.0015; price = 1.0014; proximity = 0.0010
        assert fvg_near_price(fvgs, price=1.0014, proximity=0.0010, direction="bull") is True

    def test_fvg_near_price_false_too_far(self):
        fvgs = [{"direction": "bull", "top": 1.0020, "bottom": 1.0010, "mitigated": False}]
        assert fvg_near_price(fvgs, price=1.0060, proximity=0.0010, direction="bull") is False

    def test_mitigated_fvg_ignored(self):
        fvgs = [{"direction": "bull", "top": 1.0020, "bottom": 1.0010, "mitigated": True}]
        assert fvg_near_price(fvgs, price=1.0015, proximity=0.0010, direction="bull") is False
