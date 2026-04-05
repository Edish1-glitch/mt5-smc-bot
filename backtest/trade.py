"""
backtest/trade.py — Trade dataclass.

Represents a single completed or open trade.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional
import pandas as pd


@dataclass
class Trade:
    # Identity
    symbol:    str
    direction: str   # 'bull' (long) or 'bear' (short)

    # Execution prices
    entry_price: float
    sl_price:    float
    tp_price:    float

    # Timestamps
    entry_time: pd.Timestamp
    exit_time:  Optional[pd.Timestamp] = None

    # Position sizing
    lot_size:   float = 0.0
    risk_usd:   float = 0.0   # dollars risked

    # Outcome
    exit_price: Optional[float] = None
    result:     Optional[str]   = None   # 'win' | 'loss' | 'open'
    pnl_usd:    float           = 0.0   # realized P&L in USD

    def close(self, exit_price: float, exit_time: pd.Timestamp, pip_value: float, pip_size: float) -> None:
        """
        Record trade exit (hit SL or TP).

        pnl_usd is calculated as:
          (exit_price - entry_price) / pip_size * pip_value * lot_size  (for longs)
        """
        self.exit_price = exit_price
        self.exit_time  = exit_time

        if self.direction == "bull":
            pip_diff = (exit_price - self.entry_price) / pip_size
        else:
            pip_diff = (self.entry_price - exit_price) / pip_size

        self.pnl_usd = pip_diff * pip_value * self.lot_size

        if self.direction == "bull":
            self.result = "win" if exit_price >= self.tp_price else "loss"
        else:
            self.result = "win" if exit_price <= self.tp_price else "loss"

    @property
    def is_open(self) -> bool:
        return self.result is None

    @property
    def sl_distance(self) -> float:
        return abs(self.entry_price - self.sl_price)

    @property
    def tp_distance(self) -> float:
        return abs(self.tp_price - self.entry_price)

    @property
    def risk_reward(self) -> float:
        if self.sl_distance == 0:
            return 0.0
        return self.tp_distance / self.sl_distance
