"""Walk-forward: rolling windows, only out-of-sample results, optional calibration."""

import pandas as pd
import pytest

from src import indicators as ind
from src.backtest.engine import BacktestConfig
from src.backtest.walkforward import make_windows, walk_forward
from tests.bt_helpers import random_walk

N_BARS = 6 * 261  # about 6 years of business days from 2015-01-02
PRICES = {"AAA": random_walk(N_BARS, seed=3), "BBB": random_walk(N_BARS, seed=4)}
SECTORS = {"AAA": "Tech", "BBB": "Health"}
CONFIG = BacktestConfig(initial_capital=10_000.0)


def breakout(n: int):
    def strategy(prices):
        return {
            s: pd.DataFrame(
                {
                    "entry": df["close"] > ind.donchian_high(df["high"], n),
                    "exit": df["close"] < ind.donchian_low(df["low"], 10),
                    "stop_distance": 2.5 * ind.atr(df, 20),
                }
            )
            for s, df in prices.items()
        }

    return strategy


def test_make_windows_three_years_train_one_year_test():
    dates = pd.bdate_range("2015-01-02", periods=N_BARS)
    windows = make_windows(dates, train_years=3, test_years=1)
    assert windows[0][0] == pd.Timestamp("2018-01-02")
    assert windows[0][1] == pd.Timestamp("2019-01-01")  # last bar before 2019-01-02
    assert windows[1][0] == pd.Timestamp("2019-01-02")
    assert windows[-1][1] == dates[-1]  # last (partial) window ends at the last bar
    assert len(windows) == 3


def test_walk_forward_reports_only_out_of_sample():
    result = walk_forward(breakout(20), PRICES, CONFIG, SECTORS)
    first_test = result.windows["test_start"].iloc[0]
    assert result.equity.index[0] == first_test
    assert len(result.trades) > 0
    assert (result.trades["entry_date"] >= first_test).all()
    # every trade is opened and closed inside one test window
    for _, w in result.windows.iterrows():
        inside = result.trades[
            (result.trades["entry_date"] >= w["test_start"])
            & (result.trades["entry_date"] <= w["test_end"])
        ]
        assert (inside["exit_date"] <= w["test_end"]).all()
        assert len(inside) == w["n_trades"]
    s = result.summary
    for key in ("cagr", "sharpe", "max_drawdown", "profit_factor", "expectancy_r", "win_rate"):
        assert key in s
    assert s["n_trades"] == len(result.trades)
    assert s["n_windows"] == 3
    assert 0.0 <= s["windows_profitable_pct"] <= 1.0
    # chained OOS equity = product of the window returns
    chained = (1 + result.windows["return"]).prod() * CONFIG.initial_capital
    assert result.equity.iloc[-1] == pytest.approx(chained)


def test_calibration_only_sees_training_data():
    seen = []

    def calibrate(train_prices):
        seen.append(max(df.index.max() for df in train_prices.values()))
        return breakout(20 if len(seen) % 2 else 30)

    result = walk_forward(breakout(20), PRICES, CONFIG, SECTORS, calibrate=calibrate)
    assert len(seen) == len(result.windows)
    for last_train_day, start in zip(seen, result.windows["test_start"]):
        assert last_train_day < start
