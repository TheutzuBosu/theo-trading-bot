"""Unit tests for Poarta 1 B evaluation and calibration (src/backtest/gate1_daytrading.py)."""

from __future__ import annotations

import pandas as pd

from src.backtest.gate1_daytrading import (
    D1_DEFAULT_PAIR,
    calibrate_d1_monthly,
    choose_pair_for_window,
    evaluate_gate1_daytrading,
    passes,
    perturb_d1_pair,
    perturb_d1b_params,
)
from src.strategies.intraday_d1 import D1bParams


def test_choose_pair_for_window_selects_best_sharpe_and_handles_ties_and_min_trades():
    # Normal selection: (20, 1.25) has highest Sharpe and >= 100 trades
    cands = {
        (14, 1.0): (1.10, 140),
        (20, 1.25): (1.45, 115),
        (7, 0.75): (2.10, 85),  # < 100 trades -> ineligible
    }
    L, m, sh, n_tr, used_def = choose_pair_for_window(cands)
    assert (L, m) == (20, 1.25)
    assert sh == 1.45
    assert n_tr == 115
    assert used_def is False

    # Tie between top two pairs -> fallback to default (14, 1.0)
    cands_tie = {
        (14, 1.0): (0.90, 140),
        (10, 1.0): (1.50, 120),
        (20, 1.25): (1.50, 130),
    }
    L, m, _, _, used_def = choose_pair_for_window(cands_tie)
    assert (L, m) == D1_DEFAULT_PAIR
    assert used_def is True

    # All pairs < 100 trades -> fallback to default
    cands_few = {
        (14, 1.0): (1.20, 50),
        (20, 1.25): (1.80, 99),
    }
    L, m, _, _, used_def = choose_pair_for_window(cands_few)
    assert (L, m) == D1_DEFAULT_PAIR
    assert used_def is True


def test_perturb_d1_and_d1b_parameters():
    p_d1 = perturb_d1_pair(14, 1.0)
    assert p_d1 == {
        "L-20%": (11, 1.0),
        "L+20%": (17, 1.0),
        "m-20%": (14, 0.8),
        "m+20%": (14, 1.2),
    }

    p_d1b = perturb_d1b_params(D1bParams())
    assert len(p_d1b) == 18
    by_label = dict(p_d1b)
    assert by_label["lookback-20%=3"].lookback == 3
    assert by_label["lookback+20%=5"].lookback == 5
    # Verify |stop_1| < |stop_0| (stop_0 < stop_1 < 0) holds in every perturbation (D29b eq. 6)
    for label, params in p_d1b:
        assert params.stop_0 < params.stop_1 < 0, f"Constraint violated in {label}"


def test_calibrate_d1_monthly_uses_only_prior_24_months():
    idx = pd.date_range("2016-01-04", "2018-02-28", freq="B").date
    # Pair A is strong in 2016-2017, Pair B only in 2018
    rets_a = pd.Series(0.002, index=idx)
    rets_a.iloc[::2] = 0.004  # positive variance and positive mean
    rets_b = pd.Series(-0.001, index=idx)
    rets_b.loc[pd.Index(idx) >= pd.Timestamp("2018-01-01").date()] = 0.010

    t_dates = pd.Series(idx[:150])  # 150 trades in 2016
    records = calibrate_d1_monthly(
        daily_rets_by_pair={(14, 1.0): rets_b, (20, 1.25): rets_a},
        trade_dates_by_pair={(14, 1.0): t_dates, (20, 1.25): t_dates},
        oos_months=[pd.Period("2018-01", freq="M")],
    )
    assert len(records) == 1
    assert (records[0].lookback_days, records[0].band_mult) == (20, 1.25)


def test_evaluate_gate1_daytrading_criteria():
    base_oos = {
        "n_trades": 450,
        "expectancy_r": 0.08,
        "t_stat": 3.10,
        "pct_years_positive": 7 / 9,
        "worst_year": -0.04,
        "sharpe": 1.35,
    }
    varied = {"L-20%": 0.04, "L+20%": 0.06, "m-20%": 0.03, "m+20%": 0.05}
    crit = evaluate_gate1_daytrading(
        oos=base_oos,
        stress_expectancy_r=0.05,
        dsr_value=0.98,
        random_pct_beaten=0.97,
        varied_expectancies=varied,
        d2_sharpe=0.80,
        unseen_expectancy_r=0.04,
    )
    assert len(crit) == 8
    assert passes(crit)

    # Failing unseen window fails D1b
    crit_fail_unseen = evaluate_gate1_daytrading(
        oos=base_oos,
        stress_expectancy_r=0.05,
        dsr_value=0.98,
        random_pct_beaten=0.97,
        varied_expectancies=varied,
        d2_sharpe=0.80,
        unseen_expectancy_r=-0.01,
    )
    assert not passes(crit_fail_unseen)
    assert not crit_fail_unseen[-1].passed
