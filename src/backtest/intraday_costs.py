"""Faza B cost model for intraday backtests (pure functions, D25).

Costs are in ETF price units (dollars per share) per side, applied on every entry and exit.
Two variants (docs/PLAN_DAYTRADING.md, "Modelul de costuri"):

- "stock": SPY/QQQ shares on Alpaca. Commission 0; half spread 0.005 $ (typical spread 1 cent) plus
  slippage 0.01 $ per side. Regulatory sell fees (FINRA TAF, < 0.0002 $/share) are inside
  the slippage.
- "cfd": US500 0.8 and US100 2.5 index points per side (independent ORB replication), converted to
  SPY/QQQ units with the index/ETF ratio (S&P 500 ~ 10.0 x SPY, Nasdaq-100 ~ 40.8 x QQQ).

Stress test: every cost x 1.5. Trades with initial risk below 2x the round-trip cost are skipped.
"""

from __future__ import annotations

from typing import Literal

Variant = Literal["stock", "cfd"]
Direction = Literal["long", "short"]

STOCK_HALF_SPREAD = 0.005
STOCK_SLIPPAGE = 0.01
CFD_POINTS = {"SPY": 0.8, "QQQ": 2.5}  # US500, US100 points per side
INDEX_PER_ETF = {"SPY": 10.0, "QQQ": 40.8}
STRESS_FACTOR = 1.5
MIN_RISK_TO_COST = 2.0


def cost_per_side(symbol: str, variant: Variant = "stock", stress: float = 1.0) -> float:
    """Spread + slippage per share for one entry or one exit, in dollars."""
    symbol = symbol.upper()
    if variant == "stock":
        base = STOCK_HALF_SPREAD + STOCK_SLIPPAGE
    elif variant == "cfd":
        if symbol not in CFD_POINTS:
            raise ValueError(f"no CFD cost for {symbol}; known: {sorted(CFD_POINTS)}")
        base = CFD_POINTS[symbol] / INDEX_PER_ETF[symbol]
    else:
        raise ValueError(f"unknown cost variant: {variant}")
    if stress < 1.0:
        raise ValueError("stress factor must be >= 1")
    return base * stress


def round_trip_cost(symbol: str, variant: Variant = "stock", stress: float = 1.0) -> float:
    """Entry + exit cost per share."""
    return 2.0 * cost_per_side(symbol, variant, stress)


def fill_price(price: float, side: Literal["buy", "sell"], per_side: float) -> float:
    """Price actually paid (buy) or received (sell) after spread and slippage."""
    if side == "buy":
        return price + per_side
    if side == "sell":
        return price - per_side
    raise ValueError(f"unknown side: {side}")


def net_pnl_per_share(entry: float, exit: float, direction: Direction, per_side: float) -> float:
    """Profit per share after costs on both sides. Long buys then sells; short sells then buys."""
    if direction == "long":
        return fill_price(exit, "sell", per_side) - fill_price(entry, "buy", per_side)
    if direction == "short":
        return fill_price(entry, "sell", per_side) - fill_price(exit, "buy", per_side)
    raise ValueError(f"unknown direction: {direction}")


def r_multiple(net_pnl: float, initial_risk: float) -> float:
    """Result in R: net profit per share divided by the initial risk per share (entry to stop)."""
    if initial_risk <= 0:
        raise ValueError("initial risk must be positive")
    return net_pnl / initial_risk


def trade_allowed(initial_risk: float, round_trip: float) -> bool:
    """Skip trades whose initial risk per share is below 2x the round-trip cost."""
    return initial_risk >= MIN_RISK_TO_COST * round_trip
