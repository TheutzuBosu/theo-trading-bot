"""Metric tests on hand-computed equity curves and trades."""

import numpy as np
import pandas as pd
import pytest

from src.backtest.engine import CostModel
from src.backtest.metrics import (
    benchmark_summary,
    buy_and_hold,
    equity_metrics,
    max_drawdown,
    trade_metrics,
)
from tests.bt_helpers import bars


def test_max_drawdown():
    # peak 110 -> trough 99: 1 - 99/110 = 10%
    assert max_drawdown([100.0, 110.0, 99.0, 120.0]) == pytest.approx(0.10)
    assert max_drawdown([100.0, 101.0, 102.0]) == 0.0


def test_equity_metrics():
    dates = pd.to_datetime(["2020-01-01", "2020-06-01", "2021-01-01", "2022-01-01"])
    equity = pd.Series([100.0, 110.0, 99.0, 121.0], index=dates)
    m = equity_metrics(equity, initial=100.0)
    assert m["total_return"] == pytest.approx(0.21)
    # 1.21 over 2 years (731 days) -> about 10% a year
    assert m["cagr"] == pytest.approx(1.21 ** (365.25 / 731) - 1)
    assert m["max_drawdown"] == pytest.approx(0.10)
    rets = np.array([0.0, 0.1, -0.1, 121 / 99 - 1])
    assert m["sharpe"] == pytest.approx(rets.mean() / rets.std(ddof=1) * np.sqrt(252))


def test_drawdown_counts_loss_from_initial_capital():
    equity = pd.Series([90.0, 95.0], index=pd.to_datetime(["2020-01-01", "2020-01-02"]))
    assert equity_metrics(equity, initial=100.0)["max_drawdown"] == pytest.approx(0.10)


def test_trade_metrics():
    trades = pd.DataFrame({"pnl": [10.0, -5.0, 20.0, -5.0], "r_multiple": [1.0, -0.5, 2.0, -0.5]})
    m = trade_metrics(trades)
    assert m["n_trades"] == 4
    assert m["win_rate"] == 0.5
    assert m["profit_factor"] == pytest.approx(3.0)  # 30 / 10
    assert m["expectancy_r"] == pytest.approx(0.5)


def test_trade_metrics_edge_cases():
    assert trade_metrics(pd.DataFrame(columns=["pnl", "r_multiple"]))["n_trades"] == 0
    only_wins = pd.DataFrame({"pnl": [1.0], "r_multiple": [0.5]})
    assert trade_metrics(only_wins)["profit_factor"] == np.inf


def test_buy_and_hold_with_costs():
    spy = bars([(100.0, 101.0, 99.0, 101.0), (101.0, 103.0, 100.0, 102.0), (102.0, 111, 101, 110)])
    equity = buy_and_hold(spy, 1_000.0, CostModel())
    shares = 1_000.0 / 100.15  # bought at the first Open + 0.15%
    assert equity.iloc[0] == pytest.approx(shares * 101.0)
    assert equity.iloc[-1] == pytest.approx(shares * 110.0 * 0.9985)  # sold at the last close
    summary = benchmark_summary(spy, 1_000.0)
    assert summary["total_return"] == pytest.approx(shares * 110.0 * 0.9985 / 1_000.0 - 1)
    assert summary["avg_exposure"] == 1.0
