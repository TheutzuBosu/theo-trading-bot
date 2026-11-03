"""Gate 1 criteria: thresholds, parameter variations and position-months."""

import numpy as np
import pandas as pd

from src.backtest.gate1 import evaluate, passes, position_months, vary_params

SPY = {"sharpe": 0.8, "cagr": 0.12, "max_drawdown": 0.34}


def good_oos(**changes) -> dict:
    oos = {
        "n_trades": 200,
        "sharpe": 1.1,
        "cagr": 0.08,
        "max_drawdown": 0.15,
        "profit_factor": 1.5,
        "expectancy_r": 0.2,
        "windows_profitable_pct": 0.7,
    }
    return {**oos, **changes}


def run(name="S1", oos=None, months=0, varied=(1.3, 1.2), beat=0.97, dd95=0.15):
    return evaluate(name, oos or good_oos(), SPY, months, list(varied), beat, dd95)


def failed(criteria) -> list[int]:
    return [c.number for c in criteria if not c.passed]


def test_all_criteria_pass():
    criteria = run()
    assert [c.number for c in criteria] == [1, 2, 3, 4, 5, 6, 7]
    assert passes(criteria)


def test_each_threshold_fails_on_its_own():
    assert failed(run(oos=good_oos(n_trades=149))) == [1]
    assert failed(run(oos=good_oos(sharpe=0.99))) == [2]  # needs SPY + 0.2 = 1.0
    assert failed(run(oos=good_oos(profit_factor=1.29))) == [3]
    assert failed(run(oos=good_oos(expectancy_r=0.09))) == [3]
    assert failed(run(oos=good_oos(windows_profitable_pct=0.59))) == [4]
    assert failed(run(varied=(1.3, 1.1))) == [5]  # strictly above 1.1
    assert failed(run(beat=0.949)) == [6]
    assert failed(run(dd95=0.20)) == [7]  # strictly below 20%


def test_criterion_2_alternative_cagr_and_drawdown():
    # Sharpe too low, but CAGR >= SPY and DD <= 0.7 * 34% = 23.8%
    assert passes(run(oos=good_oos(sharpe=0.5, cagr=0.12, max_drawdown=0.238)))
    assert failed(run(oos=good_oos(sharpe=0.5, cagr=0.12, max_drawdown=0.24))) == [2]
    assert failed(run(oos=good_oos(sharpe=0.5, cagr=0.119, max_drawdown=0.1))) == [2]


def test_missing_values_fail():
    criteria = run(
        oos=good_oos(n_trades=0, sharpe=np.nan, profit_factor=np.nan, expectancy_r=np.nan),
        varied=(),
        beat=0.0,
        dd95=np.nan,
    )
    assert failed(criteria) == [1, 2, 3, 5, 6, 7]


def test_s2_counts_position_months():
    assert failed(run("S2", oos=good_oos(n_trades=40), months=100)) == []
    assert failed(run("S2", oos=good_oos(n_trades=400), months=99)) == [1]


def test_position_months():
    trades = pd.DataFrame(
        {
            "entry_date": pd.to_datetime(["2020-01-03", "2020-01-03", "2020-01-06"]),
            "exit_date": pd.to_datetime(["2020-02-04", "2020-04-02", "2020-01-20"]),
        }
    )
    # Jan; Jan + Feb + Mar; stopped out inside January still counts once
    assert position_months(trades) == 1 + 3 + 1


def test_vary_params_rounds_integers_and_scales_floats():
    out = vary_params({"lookback": 55, "period": 2, "stop_atr": 2.5, "momentum": 252})
    assert out == [
        ("lookback", 44),
        ("lookback", 66),
        ("period", 1),  # 1.6 and 2.4 round back to 2 -> moves by one
        ("period", 3),
        ("stop_atr", 2.0),
        ("stop_atr", 3.0),
        ("momentum", 202),
        ("momentum", 302),
    ]
    assert all(isinstance(v, int) for k, v in out if k != "stop_atr")


def test_vary_params_never_goes_below_one():
    assert vary_params({"n": 1}) == [("n", 2)]
