"""Poarta 1 B evaluation and walk-forward calibration for Faza B (D29, D29b).

Implements:
- Monthly walk-forward calibration of D1 over L in {7, 10, 14, 20, 28} and
  m in {0.75, 1.0, 1.25, 1.5} on the trailing 24 calendar months (minimum 100 trades,
  highest daily net Sharpe, fallback/tie-breaker (14, 1.0)).
- +/-20% parameter perturbation generators for D1 (monthly or fixed) and D1b (9 parameters).
- The 7 pre-registered criteria of Poarta 1 B (D29) plus the unseen-window condition
  (2024-10-01 .. 2026-10-30) for D1b (D29b).
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, replace

import numpy as np
import pandas as pd

from src.backtest.gate1 import Criterion, passes
from src.strategies.intraday_d1 import D1bParams

OOS_START = "2018-01-02"
OOS_END = "2026-10-30"
D1B_UNSEEN_START = "2024-10-01"
IEX_START = "2020-08-03"

D1_L_GRID: tuple[int, ...] = (7, 10, 14, 20, 28)
D1_M_GRID: tuple[float, ...] = (0.75, 1.0, 1.25, 1.5)
D1_DEFAULT_PAIR: tuple[int, float] = (14, 1.0)

CALIBRATION_MONTHS = 24
MIN_CAL_TRADES = 100

MIN_OOS_TRADES = 300
MIN_EXPECTANCY_R = 0.05
MIN_T_STAT = 2.6
MIN_DSR = 0.95
MIN_RANDOM_BEAT = 0.95
MIN_YEARS_POSITIVE = 0.60
MIN_WORST_YEAR = -0.15
MIN_SHARPE = 1.0
PARAM_STEP = 0.20
N_TRIALS = 9


@dataclass(frozen=True)
class CalibrationRecord:
    """One OOS month's selected (L, m) pair and its 24-month training stats."""

    month: str  # "YYYY-MM"
    lookback_days: int
    band_mult: float
    train_sharpe: float
    train_trades: int
    used_default: bool


def _round_half_up(x: float) -> int:
    return int(math.floor(x + 0.5))


def _vary_int(base: int, sign: int, step: float = PARAM_STEP, minimum: int = 2) -> int:
    val = _round_half_up(base * (1.0 + sign * step))
    if val == base:
        val = base + sign
    return max(minimum, val)


def perturb_d1_pair(
    lookback_days: int, band_mult: float, step: float = PARAM_STEP
) -> dict[str, tuple[int, float]]:
    """Return the 4 single-parameter +/-step perturbations of a (L, m) pair."""
    return {
        "L-20%": (_vary_int(lookback_days, -1, step), band_mult),
        "L+20%": (_vary_int(lookback_days, +1, step), band_mult),
        "m-20%": (lookback_days, round(band_mult * (1.0 - step), 6)),
        "m+20%": (lookback_days, round(band_mult * (1.0 + step), 6)),
    }


def perturb_d1b_params(
    base: D1bParams = D1bParams(), step: float = PARAM_STEP
) -> list[tuple[str, D1bParams]]:
    """Return the 18 single-parameter +/-step perturbations of D1b (D29b).

    Parameters varied one by one: L (rounded: 3 and 5), m, sigma_target,
    first_check_min (around 42m after open), check_freq_min, exit_before_close_min,
    stop_0, stop_1, and take_profit_0.
    """
    out: list[tuple[str, D1bParams]] = []
    int_fields = (
        ("lookback", 2),
        ("first_check_min", 1),
        ("check_freq_min", 5),
        ("exit_before_close_min", 1),
    )
    float_fields = (
        "mult",
        "sigma_target",
        "stop_0",
        "stop_1",
        "take_profit_0",
    )
    for field, minimum in int_fields:
        base_val = int(getattr(base, field))
        for sign, tag in ((-1, "-20%"), (+1, "+20%")):
            if field == "first_check_min":
                # D29b: 42 minutes after open corresponds to bar 09:30 + 41m (10:11 close)
                mins_after_open = _vary_int(base_val + 1, sign, step, minimum=2)
                new_val = mins_after_open - 1
            else:
                new_val = _vary_int(base_val, sign, step, minimum=minimum)
            out.append((f"{field}{tag}={new_val}", replace(base, **{field: new_val})))

    for field in float_fields:
        base_val = float(getattr(base, field))
        for sign, tag in ((-1, "-20%"), (+1, "+20%")):
            new_val = round(base_val * (1.0 + sign * step), 6)
            out.append((f"{field}{tag}={new_val:.4g}", replace(base, **{field: new_val})))
    return out


def choose_pair_for_window(
    candidates: Mapping[tuple[int, float], tuple[float, int]],
    default_pair: tuple[int, float] = D1_DEFAULT_PAIR,
    min_trades: int = MIN_CAL_TRADES,
) -> tuple[int, float, float, int, bool]:
    """Pick the (L, m) pair with highest Sharpe among those with >= min_trades.

    `candidates` maps `(L, m)` -> `(sharpe, n_trades)` over the 24-month window.
    On ties or when no pair reaches `min_trades`, falls back to `default_pair`.
    """
    best_pair: tuple[int, float] | None = None
    best_sharpe = -math.inf
    best_trades = 0
    tied = False

    # Check default_pair first so an exact tie with default keeps default
    ordered_pairs = [default_pair] + [p for p in candidates if p != default_pair]
    for pair in ordered_pairs:
        if pair not in candidates:
            continue
        sharpe, n_trades = candidates[pair]
        if n_trades < min_trades or not np.isfinite(sharpe):
            continue
        if sharpe > best_sharpe + 1e-12:
            best_pair = pair
            best_sharpe = float(sharpe)
            best_trades = int(n_trades)
            tied = False
        elif abs(sharpe - best_sharpe) <= 1e-12 and best_pair is not None:
            tied = True

    if best_pair is None or tied:
        def_sharpe, def_trades = candidates.get(default_pair, (float("nan"), 0))
        return default_pair[0], default_pair[1], float(def_sharpe), int(def_trades), True

    return (
        best_pair[0],
        best_pair[1],
        best_sharpe,
        best_trades,
        best_pair == default_pair,
    )


def calibrate_d1_monthly(
    daily_rets_by_pair: Mapping[tuple[int, float], pd.Series],
    trade_dates_by_pair: Mapping[tuple[int, float], pd.Series],
    oos_months: list[pd.Period],
    calibration_months: int = CALIBRATION_MONTHS,
    min_trades: int = MIN_CAL_TRADES,
    default_pair: tuple[int, float] = D1_DEFAULT_PAIR,
) -> list[CalibrationRecord]:
    """Select (L, m) for each OOS month using the trailing 24 calendar months."""
    records: list[CalibrationRecord] = []
    for ym in oos_months:
        month_start = ym.start_time.date()
        train_start = (ym.start_time - pd.DateOffset(months=calibration_months)).date()
        candidates: dict[tuple[int, float], tuple[float, int]] = {}
        for pair, rets in daily_rets_by_pair.items():
            idx_dates = pd.Index(rets.index)
            mask = (idx_dates >= train_start) & (idx_dates < month_start)
            sub_rets = rets.loc[mask]
            t_dates = trade_dates_by_pair[pair]
            n_trades = int(((t_dates >= train_start) & (t_dates < month_start)).sum())
            sd = float(sub_rets.std(ddof=1)) if len(sub_rets) > 1 else 0.0
            sharpe = float(sub_rets.mean() / sd * math.sqrt(252)) if sd > 0 else float("nan")
            candidates[pair] = (sharpe, n_trades)

        L, m, sh, n_tr, used_def = choose_pair_for_window(
            candidates, default_pair=default_pair, min_trades=min_trades
        )
        records.append(
            CalibrationRecord(
                month=str(ym),
                lookback_days=L,
                band_mult=m,
                train_sharpe=sh,
                train_trades=n_tr,
                used_default=used_def,
            )
        )
    return records


def _num(x: float | None, fmt: str = ".2f") -> str:
    return "n/a" if x is None or not np.isfinite(x) else format(float(x), fmt)


def _pct(x: float | None) -> str:
    return "n/a" if x is None or not np.isfinite(x) else f"{float(x):.1%}"


def _ge(x: float | None, limit: float) -> bool:
    return x is not None and bool(np.isfinite(x)) and float(x) >= limit


def _gt(x: float | None, limit: float) -> bool:
    return x is not None and bool(np.isfinite(x)) and float(x) > limit


def evaluate_gate1_daytrading(
    oos: Mapping[str, float],
    stress_expectancy_r: float,
    dsr_value: float,
    random_pct_beaten: float,
    varied_expectancies: Mapping[str, float],
    d2_sharpe: float,
    unseen_expectancy_r: float | None = None,
) -> list[Criterion]:
    """Evaluate the 7 pre-registered criteria of Poarta 1 B (D29) plus D29b if applicable."""
    criteria: list[Criterion] = []

    # 1. >= 300 OOS trades
    n_trades = int(oos.get("n_trades", 0))
    criteria.append(
        Criterion(
            1,
            "Tranzacții OOS",
            n_trades >= MIN_OOS_TRADES,
            f"{n_trades}",
            f">= {MIN_OOS_TRADES}",
        )
    )

    # 2. Expectancy >= +0.05R with t >= 2.6, stress 1.5x > 0, and DSR >= 0.95
    exp_r = oos.get("expectancy_r", float("nan"))
    t_stat = oos.get("t_stat", float("nan"))
    c2_pass = (
        _ge(exp_r, MIN_EXPECTANCY_R)
        and _ge(t_stat, MIN_T_STAT)
        and _gt(stress_expectancy_r, 0.0)
        and _ge(dsr_value, MIN_DSR)
    )
    criteria.append(
        Criterion(
            2,
            "Expectancy net, t-stat, costuri ×1,5 și DSR",
            c2_pass,
            (
                f"E[R]={_num(exp_r, '+.3f')}R (t={_num(t_stat, '.2f')}), "
                f"E[R]×1,5={_num(stress_expectancy_r, '+.3f')}R, "
                f"DSR={_pct(dsr_value)}"
            ),
            (
                f"E[R] >= +{MIN_EXPECTANCY_R:.2f}R, t >= {MIN_T_STAT}, "
                f"E[R]×1,5 > 0, DSR >= {MIN_DSR:.0%}"
            ),
        )
    )

    # 3. Random direction test (long-only, 1000 runs, seed 42): pct_beaten >= 95%
    criteria.append(
        Criterion(
            3,
            "Testul cu direcție aleatoare (1.000 rulări)",
            _ge(random_pct_beaten, MIN_RANDOM_BEAT),
            f"{_pct(random_pct_beaten)} bătute",
            f">= {MIN_RANDOM_BEAT:.0%}",
        )
    )

    # 4. Yearly consistency: >= 60% positive years (2018-2026) and no year < -15%
    pct_pos = oos.get("pct_years_positive", float("nan"))
    worst_yr = oos.get("worst_year", float("nan"))
    c4_pass = _ge(pct_pos, MIN_YEARS_POSITIVE) and _ge(worst_yr, MIN_WORST_YEAR)
    criteria.append(
        Criterion(
            4,
            "Consistență pe ani (2018–2026)",
            c4_pass,
            f"{_pct(pct_pos)} ani pe plus, cel mai slab an {_pct(worst_yr)}",
            f">= {MIN_YEARS_POSITIVE:.0%} ani > 0 și niciun an < {MIN_WORST_YEAR:.0%}",
        )
    )

    # 5. Annualized Sharpe of daily OOS returns >= 1.0
    sharpe = oos.get("sharpe", float("nan"))
    criteria.append(
        Criterion(
            5,
            "Sharpe anualizat OOS (√252)",
            _ge(sharpe, MIN_SHARPE),
            _num(sharpe, ".2f"),
            f">= {MIN_SHARPE:.2f}",
        )
    )

    # 6. +/-20% parameter stability: expectancy > 0 in all variants
    vals = list(varied_expectancies.values())
    worst_var = min(vals) if vals else float("nan")
    n_pos = sum(1 for v in vals if np.isfinite(v) and v > 0.0)
    c6_pass = bool(vals) and n_pos == len(vals)
    criteria.append(
        Criterion(
            6,
            "Stabilitate la ±20% pe parametri",
            c6_pass,
            f"{n_pos}/{len(vals)} cu E[R] > 0 (minim {_num(worst_var, '+.3f')}R)",
            "E[R] > 0 în toate variantele",
        )
    )

    # 7. Sharpe OOS > Sharpe OOS of D2 benchmark
    c7_pass = (
        sharpe is not None
        and d2_sharpe is not None
        and bool(np.isfinite(sharpe))
        and bool(np.isfinite(d2_sharpe))
        and float(sharpe) > float(d2_sharpe)
    )
    criteria.append(
        Criterion(
            7,
            "Bate martorul D2 (ORB 5m) după Sharpe OOS",
            c7_pass,
            f"Sharpe {_num(sharpe, '.2f')} vs D2 {_num(d2_sharpe, '.2f')}",
            f"Sharpe > {_num(d2_sharpe, '.2f')}",
        )
    )

    # 8. Optional D29b unseen window (2024-10-01 .. 2026-10-30) for D1b
    if unseen_expectancy_r is not None:
        criteria.append(
            Criterion(
                8,
                "Fereastra nevăzută de autor (D29b: oct. 2024 – oct. 2026)",
                _gt(unseen_expectancy_r, 0.0),
                f"E[R]={_num(unseen_expectancy_r, '+.3f')}R",
                "E[R] > 0",
            )
        )

    return criteria


__all__ = [
    "CALIBRATION_MONTHS",
    "CalibrationRecord",
    "Criterion",
    "D1B_UNSEEN_START",
    "D1_DEFAULT_PAIR",
    "D1_L_GRID",
    "D1_M_GRID",
    "IEX_START",
    "MIN_CAL_TRADES",
    "MIN_DSR",
    "MIN_EXPECTANCY_R",
    "MIN_OOS_TRADES",
    "MIN_RANDOM_BEAT",
    "MIN_SHARPE",
    "MIN_T_STAT",
    "MIN_WORST_YEAR",
    "MIN_YEARS_POSITIVE",
    "N_TRIALS",
    "OOS_END",
    "OOS_START",
    "PARAM_STEP",
    "calibrate_d1_monthly",
    "choose_pair_for_window",
    "evaluate_gate1_daytrading",
    "passes",
    "perturb_d1_pair",
    "perturb_d1b_params",
]
