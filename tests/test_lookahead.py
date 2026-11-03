"""A strategy that looks into the future must be caught."""

import pandas as pd
import pytest

from src import indicators as ind
from src.backtest.lookahead import LookAheadError, assert_no_lookahead, find_lookahead
from src.backtest.walkforward import backtest_strategy, walk_forward
from tests.bt_helpers import random_walk

PRICES = {"AAA": random_walk(300, seed=1), "BBB": random_walk(300, seed=2)}


def _frame(df: pd.DataFrame, entry: pd.Series) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "entry": entry.fillna(False).astype(bool),
            "exit": df["close"] < ind.sma(df["close"], 10),
            "stop_distance": 2.0 * ind.atr(df, 20),
        }
    )


def honest(prices):
    return {
        s: _frame(df, df["close"] > ind.donchian_high(df["high"], 20)) for s, df in prices.items()
    }


def cheat_next_close(prices):
    """Buys when tomorrow's close is higher: uses data from the future."""
    return {s: _frame(df, df["close"].shift(-1) > df["close"]) for s, df in prices.items()}


def cheat_centered_window(prices):
    """A centered moving average silently uses the next bars."""
    return {
        s: _frame(df, df["close"] > df["close"].rolling(11, center=True).mean())
        for s, df in prices.items()
    }


def test_honest_strategy_passes():
    assert find_lookahead(honest, PRICES) == []
    assert_no_lookahead(honest, PRICES)


@pytest.mark.parametrize("cheat", [cheat_next_close, cheat_centered_window])
def test_cheating_strategy_is_caught(cheat):
    assert find_lookahead(cheat, PRICES)
    with pytest.raises(LookAheadError, match="future data"):
        assert_no_lookahead(cheat, PRICES)


def test_backtest_and_walk_forward_refuse_a_cheating_strategy():
    with pytest.raises(LookAheadError):
        backtest_strategy(cheat_next_close, PRICES)
    with pytest.raises(LookAheadError):
        walk_forward(cheat_next_close, PRICES)


def test_cheating_in_stop_distance_is_caught_too():
    def cheat_stop(prices):
        out = honest(prices)
        for s, df in prices.items():
            out[s]["stop_distance"] = (df["low"].shift(-5) - df["close"]).abs() + 1.0
        return out

    assert find_lookahead(cheat_stop, PRICES)
