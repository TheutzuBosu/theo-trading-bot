"""Gate 1 criteria (docs/PLAN.md): a strategy passes only if all seven hold on the out-of-sample
walk-forward results, after costs. Pure functions; scripts/gate1.py runs the backtests."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass

import numpy as np
import pandas as pd

MIN_TRADES = 150
MIN_POSITION_MONTHS = 100  # instead of trades, for the monthly rotation strategies
POSITION_MONTH_STRATEGIES = frozenset({"S2"})
SHARPE_MARGIN = 0.2
MAX_DD_RATIO = 0.7
MIN_PROFIT_FACTOR = 1.3
MIN_EXPECTANCY_R = 0.1
MIN_WINDOWS_PROFITABLE = 0.6
PARAM_STEP = 0.2
MIN_VARIED_PROFIT_FACTOR = 1.1  # strictly above
RANDOM_METRIC = "sharpe"
MIN_RANDOM_BEAT = 0.95
MAX_MC_DRAWDOWN_P95 = 0.20  # strictly below


@dataclass(frozen=True)
class Criterion:
    number: int
    name: str
    passed: bool
    value: str
    threshold: str


def position_months(trades: pd.DataFrame) -> int:
    """Month-ends each position was held over (entry close to exit, exit day excluded),
    at least 1 per position."""
    total = 0
    for entry, exit_ in zip(trades["entry_date"], trades["exit_date"]):
        month_ends = pd.date_range(pd.Timestamp(entry), pd.Timestamp(exit_), freq="ME")
        total += max(1, int(np.sum(month_ends < pd.Timestamp(exit_).normalize())))
    return total


def _round_half_up(x: float) -> int:
    return int(math.floor(x + 0.5))


def vary_params(params: Mapping[str, float], step: float = PARAM_STEP) -> list[tuple[str, float]]:
    """One override per parameter and direction: value * (1 -/+ step). Integer parameters are
    rounded half up; if rounding gives back the base value they move by 1 (never below 1)."""
    out: list[tuple[str, float]] = []
    for key, base in params.items():
        if isinstance(base, bool) or not isinstance(base, int | float):
            continue
        for sign in (-1, 1):
            raw = base * (1 + sign * step)
            if isinstance(base, int):
                value = _round_half_up(raw)
                if value == base:
                    value = base + sign
                if value < 1:
                    continue
            else:
                value = round(raw, 10)
            out.append((key, value))
    return out


def _pct(x: float) -> str:
    return "n/a" if x is None or not np.isfinite(x) else f"{x:.1%}"


def _num(x: float, fmt: str = ".2f") -> str:
    return "n/a" if x is None or not np.isfinite(x) else format(x, fmt)


def _ge(x: float, limit: float) -> bool:
    return x is not None and bool(np.isfinite(x)) and x >= limit


def evaluate(
    name: str,
    oos: Mapping[str, float],
    spy: Mapping[str, float],
    n_position_months: int,
    varied_profit_factors: list[float],
    random_beat: float,
    mc_drawdown_p95: float,
) -> list[Criterion]:
    """The seven Gate 1 criteria for strategy `name`.

    oos / spy: equity and trade metrics (src/backtest/metrics.py) of the walk-forward and of SPY
    buy-and-hold over the same period; random_beat: share of random-entry runs beaten on
    RANDOM_METRIC; mc_drawdown_p95: 95th percentile of the reshuffled max drawdown."""
    criteria = []

    if name in POSITION_MONTH_STRATEGIES:
        criteria.append(
            Criterion(
                1,
                "Tranzacții OOS",
                n_position_months >= MIN_POSITION_MONTHS,
                f"{n_position_months} poziții-lună ({oos['n_trades']} tranzacții)",
                f">= {MIN_POSITION_MONTHS} poziții-lună",
            )
        )
    else:
        criteria.append(
            Criterion(
                1,
                "Tranzacții OOS",
                oos["n_trades"] >= MIN_TRADES,
                f"{oos['n_trades']}",
                f">= {MIN_TRADES}",
            )
        )

    by_sharpe = _ge(oos["sharpe"], spy["sharpe"] + SHARPE_MARGIN)
    by_cagr_dd = _ge(oos["cagr"], spy["cagr"]) and oos["max_drawdown"] <= (
        MAX_DD_RATIO * spy["max_drawdown"]
    )
    criteria.append(
        Criterion(
            2,
            "Mai bună decât SPY ajustat la risc",
            by_sharpe or by_cagr_dd,
            f"Sharpe {_num(oos['sharpe'])} vs {_num(spy['sharpe'])}; "
            f"CAGR {_pct(oos['cagr'])} vs {_pct(spy['cagr'])}; "
            f"DD {_pct(oos['max_drawdown'])} vs {_pct(spy['max_drawdown'])}",
            f"Sharpe >= {_num(spy['sharpe'] + SHARPE_MARGIN)}, sau CAGR >= "
            f"{_pct(spy['cagr'])} și DD <= {_pct(MAX_DD_RATIO * spy['max_drawdown'])}",
        )
    )

    criteria.append(
        Criterion(
            3,
            "Profit factor și expectancy",
            _ge(oos["profit_factor"], MIN_PROFIT_FACTOR)
            and _ge(oos["expectancy_r"], MIN_EXPECTANCY_R),
            f"PF {_num(oos['profit_factor'])}; expectancy {_num(oos['expectancy_r'], '+.2f')}R",
            f"PF >= {MIN_PROFIT_FACTOR}, expectancy >= +{MIN_EXPECTANCY_R}R",
        )
    )

    criteria.append(
        Criterion(
            4,
            "Ferestre walk-forward profitabile",
            _ge(oos["windows_profitable_pct"], MIN_WINDOWS_PROFITABLE),
            _pct(oos["windows_profitable_pct"]),
            f">= {MIN_WINDOWS_PROFITABLE:.0%}",
        )
    )

    worst = min(varied_profit_factors) if varied_profit_factors else np.nan
    criteria.append(
        Criterion(
            5,
            f"Parametri la ±{PARAM_STEP:.0%}",
            bool(varied_profit_factors)
            and all(
                np.isfinite(pf) and pf > MIN_VARIED_PROFIT_FACTOR for pf in varied_profit_factors
            ),
            f"PF minim {_num(worst)} din {len(varied_profit_factors)} variante",
            f"PF > {MIN_VARIED_PROFIT_FACTOR} în toate",
        )
    )

    criteria.append(
        Criterion(
            6,
            "Bate intrările aleatoare",
            _ge(random_beat, MIN_RANDOM_BEAT),
            f"{_pct(random_beat)} din rulări (după Sharpe)",
            f">= {MIN_RANDOM_BEAT:.0%}",
        )
    )

    criteria.append(
        Criterion(
            7,
            "Monte Carlo: drawdown p95",
            mc_drawdown_p95 is not None
            and bool(np.isfinite(mc_drawdown_p95))
            and mc_drawdown_p95 < MAX_MC_DRAWDOWN_P95,
            _pct(mc_drawdown_p95),
            f"< {MAX_MC_DRAWDOWN_P95:.0%}",
        )
    )
    return criteria


def passes(criteria: list[Criterion]) -> bool:
    return all(c.passed for c in criteria)
