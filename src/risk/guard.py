"""Hard-coded intraday risk guard for Faza B (D27, D31, `docs/GHID_EXECUTIE_AGENTI.md`).

Rules enforced in order (none are configurable from `.env`):
1. Kill switch active -> block.
2. Account drawdown from peak <= -15% -> block (triggers KILL).
3. Daily PnL <= -2% -> block new entries for the rest of the session.
4. Symbol must be in `ALLOWED_SYMBOLS` (`SPY`, `QQQ` and their inverse/leveraged ETFs `SH`, `SDS`,
   `SSO`, `PSQ`, `QID`, `QLD` per D31).
5. Direction must be `"long"` or `"short"`.
6. Every order must carry a valid stop-loss on the losing side of `entry_price`.
7. FOMC blackout window (+/-30 minutes around Fed statement) -> block.
8. Last 15 minutes of session (`minutes_to_close <= 15`) -> block new entries.
9. Current bid-ask spread > 2x typical spread -> block.
10. Max 1 open position per underlying index family (`SPY` family vs `QQQ` family).
11. Total exposure after order <= `MAX_TOTAL_EXPOSURE` (`2.0x` equity).
12. Dollar risk of the order (`qty * |entry_price - stop|`) <= `0.5%` of equity.
13. Initial risk per share >= `2x` round-trip cost (`trade_allowed`).

No daily trade count limit is imposed: the bot may take as many valid setups per day as pass
analysis and the 13 risk rules above (D31).
"""

from __future__ import annotations

import math
from collections.abc import Iterable

import pandas as pd

from src.backtest.fomc import fomc_blocked
from src.backtest.intraday_costs import round_trip_cost, trade_allowed

MAX_RISK_PER_TRADE_PCT: float = 0.005
MAX_DAILY_LOSS_PCT: float = -0.02
MAX_DRAWDOWN_KILL_PCT: float = -0.15
MAX_POSITIONS_PER_SYMBOL: int = 1
MAX_TOTAL_EXPOSURE: float = 2.0
NO_ENTRY_LAST_MINUTES: int = 15
MAX_SPREAD_MULTIPLIER: float = 2.0

ALLOWED_SYMBOLS: frozenset[str] = frozenset({"SPY", "QQQ", "SH", "SDS", "SSO", "PSQ", "QID", "QLD"})

SYMBOL_FAMILY: dict[str, str] = {
    "SPY": "SPY",
    "SH": "SPY",
    "SDS": "SPY",
    "SSO": "SPY",
    "QQQ": "QQQ",
    "PSQ": "QQQ",
    "QID": "QQQ",
    "QLD": "QQQ",
}


def symbol_family(symbol: str) -> str:
    """Return the underlying index family ('SPY' or 'QQQ') for any allowed ETF."""
    sym = str(symbol).upper()
    return SYMBOL_FAMILY.get(sym, sym)


def _is_fomc_time(timestamp: pd.Timestamp | str | None) -> bool:
    if timestamp is None:
        return False
    ts = pd.Timestamp(timestamp)
    if ts.tz is None:
        ts = ts.tz_localize("America/New_York")
    else:
        ts = ts.tz_convert("America/New_York")
    return bool(fomc_blocked(pd.DatetimeIndex([ts]))[0])


def evaluate_order_risk(
    *,
    symbol: str,
    direction: str,
    entry_price: float,
    stop: float | None,
    qty: float,
    equity: float,
    daily_pnl_pct: float = 0.0,
    drawdown_pct: float = 0.0,
    kill_switch_active: bool = False,
    open_positions: Iterable[str] = (),
    current_exposure: float = 0.0,
    minutes_to_close: float = 120.0,
    current_spread: float = 0.01,
    typical_spread: float = 0.01,
    timestamp: pd.Timestamp | str | None = None,
) -> tuple[bool, str]:
    """Evaluate all 13 hard-coded intraday risk rules before placing an entry order."""
    # a. Kill switch
    if kill_switch_active:
        return False, "KILL switch activ"

    # b. Max drawdown (-15%)
    if drawdown_pct <= MAX_DRAWDOWN_KILL_PCT:
        return False, "Drawdown maxim atins (-15%): KILL"

    # c. Daily loss limit (-2%)
    if daily_pnl_pct <= MAX_DAILY_LOSS_PCT:
        return False, "Limita zilnică de pierdere (-2%) a fost atinsă"

    # d. Allowed symbol
    sym = str(symbol).upper()
    if sym not in ALLOWED_SYMBOLS:
        return False, f"Simbol nepermis: {sym}"

    # e. Direction
    dir_norm = str(direction).lower()
    if dir_norm not in ("long", "short"):
        return False, f"Direcție invalidă: {direction}"

    # f. Stop-loss presence and side
    if stop is None or not math.isfinite(stop) or stop <= 0 or entry_price <= 0 or qty <= 0:
        return False, "Ordin fără stop-loss valid pe partea pierzătoare"
    if dir_norm == "long" and stop >= entry_price:
        return False, "Ordin fără stop-loss valid sub prețul de intrare"
    if dir_norm == "short" and stop <= entry_price:
        return False, "Ordin fără stop-loss valid deasupra prețului de intrare"

    # g. FOMC blackout (+/-30 min)
    if _is_fomc_time(timestamp):
        return False, "Veto FOMC: ±30 min de anunțul Fed"

    # h. No entries in the last 15 minutes of the session
    if minutes_to_close <= NO_ENTRY_LAST_MINUTES:
        return False, "Ultimele 15 minute ale sesiunii: fără intrări noi"

    # i. Spread check (<= 2x typical spread)
    if typical_spread > 0 and current_spread > MAX_SPREAD_MULTIPLIER * typical_spread:
        return False, "Spread curent > 2x spread-ul tipic"

    # j. Max 1 open position per symbol family (SPY family vs QQQ family)
    fam = symbol_family(sym)
    open_families = {symbol_family(s) for s in open_positions}
    if sym in {str(s).upper() for s in open_positions} or fam in open_families:
        return False, f"Există deja o poziție deschisă pe familia {fam} ({sym})"

    # k. Total exposure cap (2x equity)
    if equity <= 0:
        return False, "Capital invalid (equity <= 0)"
    order_notional = float(qty) * float(entry_price)
    if (float(current_exposure) + order_notional) / float(equity) > MAX_TOTAL_EXPOSURE + 1e-9:
        return False, "Expunerea depășește plafonul permis"

    # l. Risk per trade cap (0.5% of equity)
    initial_risk_per_share = abs(float(entry_price) - float(stop))
    risk_dollars = float(qty) * initial_risk_per_share
    if risk_dollars / float(equity) > MAX_RISK_PER_TRADE_PCT + 1e-6:
        return False, "Riscul pe tranzacție depășește 0,5% din capital"

    # m. Initial risk >= 2x round-trip cost
    rt_cost = round_trip_cost(fam, "stock")
    if not trade_allowed(initial_risk_per_share, rt_cost):
        return False, "Risc inițial < 2x costul dus-întors"

    return True, "OK"


def can_move_stop(current_stop: float, new_stop: float, direction: str = "long") -> bool:
    """Return True only if `new_stop` tightens the stop (never widens it)."""
    if not (math.isfinite(current_stop) and math.isfinite(new_stop)):
        return False
    if current_stop <= 0 or new_stop <= 0:
        return False
    dir_norm = str(direction).lower()
    if dir_norm == "long":
        return float(new_stop) > float(current_stop)
    if dir_norm == "short":
        return float(new_stop) < float(current_stop)
    raise ValueError(f"Unknown direction: {direction}")
