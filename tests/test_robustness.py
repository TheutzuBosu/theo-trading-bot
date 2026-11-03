"""Monte Carlo and random-entry test."""

import numpy as np
import pandas as pd
import pytest

from src.backtest.engine import BacktestConfig
from src.backtest.panel import MarketPanel, SignalPanel
from src.backtest.robustness import monte_carlo, random_entry_test, trade_returns
from tests.bt_helpers import random_walk

TRADES = pd.DataFrame({"pnl": [10.0, -5.0, 20.0, -10.0], "equity_at_entry": [100.0] * 4})


def test_trade_returns():
    assert trade_returns(TRADES).tolist() == [0.1, -0.05, 0.2, -0.1]


def test_monte_carlo_drawdown_bounds():
    mc = monte_carlo(TRADES, n_runs=1000, seed=7)
    assert len(mc.drawdowns) == 1000
    # the -10% trade alone gives DD 10%; both losses in a row: 1 - 0.95*0.9 = 14.5%
    assert mc.drawdowns.min() == pytest.approx(0.10)
    assert mc.drawdowns.max() == pytest.approx(0.145)
    s = mc.summary()
    assert s["drawdown_p5"] <= s["drawdown_p50"] <= s["drawdown_p95"]
    assert s["return_p5"] <= s["return_p50"] <= s["return_p95"]


def test_monte_carlo_is_reproducible_and_supports_trade_count():
    a = monte_carlo(TRADES, n_runs=200, seed=1, n_trades=10)
    b = monte_carlo(TRADES, n_runs=200, seed=1, n_trades=10)
    assert np.array_equal(a.returns, b.returns)
    assert np.array_equal(a.drawdowns, b.drawdowns)


def _oracle_panels(n=400):
    """Two symbols; 'oracle' entries placed right before the Open rises > 1% (cheating on
    purpose, built directly as signals), exit after one bar."""
    prices = {"AAA": random_walk(n, seed=5, drift=0.0), "BBB": random_walk(n, seed=6, drift=0.0)}
    panel = MarketPanel.from_frames(prices)
    signals = {}
    for s, df in prices.items():
        future_gain = df["open"].shift(-2) / df["open"].shift(-1) - 1
        signals[s] = pd.DataFrame(
            {
                "entry": (future_gain > 0.01).fillna(False),
                "exit": True,
                "stop_distance": 0.05 * df["close"],
            }
        )
    return panel, SignalPanel.from_frames(signals, panel)


def test_random_entry_test_separates_edge_from_luck():
    panel, signals = _oracle_panels()
    config = BacktestConfig(initial_capital=10_000.0)
    result = random_entry_test(panel, signals, config, n_runs=50, seed=3)
    assert len(result.random) == 50
    assert result.strategy["n_trades"] > 20
    assert result.beats["total_return"] >= 0.95
    assert result.beats["expectancy_r"] >= 0.95


def test_random_entry_result_fields():
    panel, signals = _oracle_panels()
    n_entries = int(signals.entry[:-1].sum())
    result = random_entry_test(
        panel, signals, BacktestConfig(initial_capital=10_000.0), n_runs=5, seed=1
    )
    assert result.strategy["n_trades"] <= n_entries
    assert set(result.beats) == {"total_return", "sharpe", "profit_factor", "expectancy_r"}
