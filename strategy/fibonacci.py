"""
strategy/fibonacci.py — Fibonacci retracement levels for entry/SL/TP.

Drawn from the BOS impulse swing points:

  For a LONG setup (bullish BOS):
    Swing Low  = 100%  (SL placed here — full invalidation)
    Swing High =   0%  (TP placed here — origin of the move)
    Entry      =  75%  → impulse_high - 0.75 * (impulse_high - impulse_low)

  For a SHORT setup (bearish BOS):
    Swing High = 100%  (SL placed here)
    Swing Low  =   0%  (TP placed here)
    Entry      =  75%  → impulse_low + 0.75 * (impulse_high - impulse_low)

The key insight: the 75% level is a deep retracement that often coincides
with the FVG / Order Block from the impulse move.
"""

from dataclasses import dataclass


@dataclass
class FibLevels:
    direction: str        # 'bull' or 'bear'
    impulse_low:  float   # Fib 100% anchor for bulls / Fib 0% anchor for bears
    impulse_high: float   # Fib 0%  anchor for bulls / Fib 100% anchor for bears
    entry:  float         # 75% retracement
    sl:     float         # 100% (the swing that invalidates the setup)
    tp:     float         # 0%  (the origin / target)

    @property
    def sl_distance(self) -> float:
        return abs(self.entry - self.sl)

    @property
    def tp_distance(self) -> float:
        return abs(self.tp - self.entry)

    @property
    def risk_reward(self) -> float:
        if self.sl_distance == 0:
            return 0.0
        return self.tp_distance / self.sl_distance


def calculate_fib_levels(direction: str, impulse_low: float, impulse_high: float) -> FibLevels:
    """
    Calculate entry, SL, and TP from a BOS impulse swing.

    Parameters
    ----------
    direction    : 'bull' or 'bear'
    impulse_low  : swing low of the impulse (Fib 100% for long setups)
    impulse_high : swing high of the impulse (Fib 0% for long setups)

    Returns
    -------
    FibLevels with entry at 75%, SL at 100%, TP at 0%.
    """
    span = impulse_high - impulse_low

    if direction == "bull":
        entry = impulse_high - 0.75 * span   # 75% retracement down from high
        sl    = impulse_low                   # 100% — setup fully invalidated
        tp    = impulse_high                  # 0%  — back to the swing high
    else:  # bear
        entry = impulse_low + 0.75 * span    # 75% retracement up from low
        sl    = impulse_high                  # 100% — setup fully invalidated
        tp    = impulse_low                   # 0%  — back to the swing low

    return FibLevels(
        direction=direction,
        impulse_low=impulse_low,
        impulse_high=impulse_high,
        entry=entry,
        sl=sl,
        tp=tp,
    )


def price_at_entry_zone(current_price: float, fib: FibLevels, buffer: float) -> bool:
    """
    Return True if current_price is within `buffer` of the 75% entry level.
    """
    return abs(current_price - fib.entry) <= buffer
