"""
backtest/filters.py — Post-hoc trade filters applied at entry decision time.

These filters do NOT affect signal pre-computation, so changing them
re-uses the cached BOS / sweeps / FVGs from signal_cache.

All filters operate on a single bar timestamp + a small running state dict.
"""

from __future__ import annotations
import pandas as pd

# pytz is installed; use it for Israel time conversion
try:
    import pytz
    IL_TZ = pytz.timezone("Asia/Jerusalem")
except ImportError:
    pytz = None
    IL_TZ = None


# Day-of-week constants — Sunday=0 ... Saturday=6, matching JS Date convention
SUN, MON, TUE, WED, THU, FRI, SAT = range(7)
DEFAULT_WEEKDAYS = {SUN, MON, TUE, WED, THU, FRI}  # Sun-Fri (Israel work week)


def _to_il_hour(ts: pd.Timestamp) -> int:
    """Convert a UTC pd.Timestamp to the hour-of-day in Israel time (handles DST)."""
    if IL_TZ is None:
        return ts.hour  # fallback: UTC
    if ts.tzinfo is None:
        ts = ts.tz_localize("UTC")
    return ts.tz_convert(IL_TZ).hour


def _to_il_weekday(ts: pd.Timestamp) -> int:
    """Convert a UTC pd.Timestamp to weekday in Israel time (Sun=0..Sat=6)."""
    if IL_TZ is None:
        py_weekday = ts.weekday()  # Mon=0..Sun=6
    else:
        if ts.tzinfo is None:
            ts = ts.tz_localize("UTC")
        py_weekday = ts.tz_convert(IL_TZ).weekday()
    # Convert Python weekday (Mon=0..Sun=6) to JS-style (Sun=0..Sat=6)
    return (py_weekday + 1) % 7


def passes_hours(ts: pd.Timestamp, start_hour: int, end_hour: int) -> bool:
    """
    Return True if the timestamp's Israel-local hour is within [start, end].
    Inclusive on both sides. Wraps around midnight if start > end.
    """
    if start_hour == 0 and end_hour == 23:
        return True
    h = _to_il_hour(ts)
    if start_hour <= end_hour:
        return start_hour <= h <= end_hour
    # Wrap-around (e.g. 22:00–04:00)
    return h >= start_hour or h <= end_hour


def passes_weekday(ts: pd.Timestamp, allowed: set[int]) -> bool:
    """Return True if the bar's Israel-local weekday is in the allowed set."""
    if not allowed or len(allowed) == 7:
        return True
    return _to_il_weekday(ts) in allowed


class DailyTradeCounter:
    """Stateful counter that limits trades per calendar day (Israel time)."""

    def __init__(self, max_per_day: int = 0):
        # max_per_day=0 means unlimited
        self.max = max_per_day
        self._current_day = None
        self._count = 0

    def can_take(self, ts: pd.Timestamp) -> bool:
        if self.max <= 0:
            return True
        if IL_TZ is None:
            day = ts.date()
        else:
            if ts.tzinfo is None:
                ts = ts.tz_localize("UTC")
            day = ts.tz_convert(IL_TZ).date()
        if day != self._current_day:
            self._current_day = day
            self._count = 0
        return self._count < self.max

    def record(self, ts: pd.Timestamp) -> None:
        if self.max <= 0:
            return
        if IL_TZ is None:
            day = ts.date()
        else:
            if ts.tzinfo is None:
                ts = ts.tz_localize("UTC")
            day = ts.tz_convert(IL_TZ).date()
        if day != self._current_day:
            self._current_day = day
            self._count = 0
        self._count += 1
