"""Position sizing and portfolio limits used by the backtester.

Stub of the risk guard until etapa 4. The real rules will live in src/risk/guard.py with the
same `size_position` signature; then the engine imports it from there and this file goes away,
so the backtest sizes positions exactly like the live bot.
"""

from __future__ import annotations

from typing import Final

MAX_RISK_PER_TRADE: Final = 0.01
DEFAULT_RISK_PER_TRADE: Final = 0.005
MAX_POSITION_NOTIONAL: Final = 0.20
MAX_OPEN_POSITIONS: Final = 5
MAX_PER_SECTOR: Final = 2


def size_position(
    entry: float, stop: float, equity: float, config_risk: float = DEFAULT_RISK_PER_TRADE
) -> float:
    """Quantity (fractional shares) risking min(config_risk, MAX_RISK_PER_TRADE) of equity
    between entry and stop, capped at MAX_POSITION_NOTIONAL of equity. 0 if inputs are invalid."""
    if entry <= 0 or equity <= 0 or stop <= 0 or stop >= entry or config_risk <= 0:
        return 0.0
    risk = min(config_risk, MAX_RISK_PER_TRADE)
    by_risk = equity * risk / (entry - stop)
    by_notional = equity * MAX_POSITION_NOTIONAL / entry
    return min(by_risk, by_notional)


def portfolio_rejection(n_open: int, n_in_sector: int) -> str | None:
    """Reason code if a new position would break the portfolio limits, else None."""
    if n_open >= MAX_OPEN_POSITIONS:
        return "max_positions"
    if n_in_sector >= MAX_PER_SECTOR:
        return "max_sector"
    return None
