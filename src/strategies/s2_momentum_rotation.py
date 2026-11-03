"""S2 Momentum Rotation. On the first trading day of each month the universe is ranked by the
12-1 month return; entries are the top 5 among stocks with Close > SMA200 (none if SPY < SMA200).
A held stock exits at the rebalance if it is no longer in the top 10 of the universe ranking.
Catastrophe stop: entry - 3*ATR(20)."""

from __future__ import annotations

from collections.abc import Mapping

import numpy as np
import pandas as pd

from src import indicators as ind
from src.strategies.common import (
    StrategyParams,
    benchmark_uptrend,
    describe,
    signal_frame,
    split_benchmark,
)

TITLE = "S2 Momentum Rotation"


class Params(StrategyParams):
    momentum_lookback: int
    momentum_skip: int
    sma_filter: int
    top_n: int
    exit_rank: int
    atr_period: int
    stop_atr: float


def first_trading_days(calendar: pd.DatetimeIndex) -> pd.Series:
    """True on the first bar of each month. The first bar of the data is not flagged (the
    previous bar is unknown)."""
    month = calendar.to_period("M")
    flags = np.zeros(len(calendar), dtype=bool)
    flags[1:] = month[1:] != month[:-1]
    return pd.Series(flags, index=calendar)


def signals(prices: Mapping[str, pd.DataFrame], params: Params) -> dict[str, pd.DataFrame]:
    stocks, spy = split_benchmark(prices)
    if not stocks:
        return {}
    calendar = pd.DatetimeIndex(sorted(set().union(*(df.index for df in prices.values()))))

    def wide(fn) -> pd.DataFrame:
        return pd.DataFrame({s: fn(df).reindex(calendar) for s, df in stocks.items()})

    close = wide(lambda df: df["close"])
    momentum = wide(
        lambda df: ind.momentum_12_1(df["close"], params.momentum_lookback, params.momentum_skip)
    )
    sma = wide(lambda df: ind.sma(df["close"], params.sma_filter))

    rank = momentum.rank(axis=1, ascending=False, method="first")  # 1 = strongest
    eligible = (close > sma) & momentum.notna()
    eligible_rank = momentum.where(eligible).rank(axis=1, ascending=False, method="first")

    rebalance = first_trading_days(calendar)
    spy_ok = benchmark_uptrend(spy, calendar, params.sma_filter)
    entry = (eligible_rank <= params.top_n).mul(rebalance & spy_ok, axis=0)
    exit_ = (~(rank <= params.exit_rank)).mul(rebalance, axis=0)  # also exits if unranked

    out = {}
    for sym, df in stocks.items():
        idx = df.index
        entry_s = entry[sym].reindex(idx).astype(bool)
        reason = describe(
            entry_s,
            f"{TITLE}: locul {{rank:.0f}} după randamentul 12-1 luni ({{mom:.1%}}); "
            f"Close > SMA{params.sma_filter}; SPY > SMA{params.sma_filter}; rebalansare lunară",
            rank=rank[sym].reindex(idx),
            mom=momentum[sym].reindex(idx),
        )
        out[sym] = signal_frame(
            entry=entry_s,
            exit=exit_[sym].reindex(idx).astype(bool),
            stop_distance=params.stop_atr * ind.atr(df, params.atr_period),
            score=momentum[sym].reindex(idx),
            entry_reason=reason,
        )
    return out
