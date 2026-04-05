"""Tests for Fibonacci level calculation."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pytest
from strategy.fibonacci import calculate_fib_levels, price_at_entry_zone


class TestFibLevels:
    def test_bull_fib_levels(self):
        fib = calculate_fib_levels("bull", impulse_low=1.0000, impulse_high=1.0100)
        span = 1.0100 - 1.0000  # = 0.0100
        assert fib.entry == pytest.approx(1.0100 - 0.75 * span)   # 1.0025
        assert fib.sl    == pytest.approx(1.0000)
        assert fib.tp    == pytest.approx(1.0100)

    def test_bear_fib_levels(self):
        fib = calculate_fib_levels("bear", impulse_low=1.0000, impulse_high=1.0100)
        span = 0.0100
        assert fib.entry == pytest.approx(1.0000 + 0.75 * span)   # 1.0075
        assert fib.sl    == pytest.approx(1.0100)
        assert fib.tp    == pytest.approx(1.0000)

    def test_rr_is_positive(self):
        fib = calculate_fib_levels("bull", impulse_low=1.0000, impulse_high=1.0100)
        assert fib.risk_reward > 0

    def test_bull_rr_approximately_1_to_3(self):
        # Entry at 75%, SL at 100%, TP at 0%
        # sl_dist = entry - sl = 1.0025 - 1.0000 = 0.0025
        # tp_dist = tp - entry = 1.0100 - 1.0025 = 0.0075
        # R:R = 0.0075 / 0.0025 = 3.0
        fib = calculate_fib_levels("bull", impulse_low=1.0000, impulse_high=1.0100)
        assert fib.risk_reward == pytest.approx(3.0, abs=0.01)


class TestEntryZone:
    def test_price_in_entry_zone(self):
        fib = calculate_fib_levels("bull", impulse_low=1.0000, impulse_high=1.0100)
        # entry = 1.0025, buffer = 0.0005
        assert price_at_entry_zone(1.0027, fib, buffer=0.0005) is True

    def test_price_outside_entry_zone(self):
        fib = calculate_fib_levels("bull", impulse_low=1.0000, impulse_high=1.0100)
        assert price_at_entry_zone(1.0060, fib, buffer=0.0005) is False
