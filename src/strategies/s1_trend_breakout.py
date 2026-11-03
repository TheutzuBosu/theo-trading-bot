"""S1 Trend Breakout. Filter: SPY > SMA200 and Close > SMA200. Entry: Close > highest high of the
previous 55 days. Stop: entry - 2.5*ATR(20). Exit: Close < lowest low of the previous 20 days."""

from __future__ import annotations

from collections.abc import Mapping

import pandas as pd

from src import indicators as ind
from src.strategies.common import (
    StrategyParams,
    benchmark_uptrend,
    describe,
    signal_frame,
    split_benchmark,
)

TITLE = "S1 Trend Breakout"


class Params(StrategyParams):
    sma_filter: int
    entry_lookback: int
    exit_lookback: int
    atr_period: int
    stop_atr: float


def signals(prices: Mapping[str, pd.DataFrame], params: Params) -> dict[str, pd.DataFrame]:
    stocks, spy = split_benchmark(prices)
    out = {}
    for sym, df in stocks.items():
        close = df["close"]
        spy_ok = benchmark_uptrend(spy, df.index, params.sma_filter)
        sma = ind.sma(close, params.sma_filter)
        upper = ind.donchian_high(df["high"], params.entry_lookback)
        lower = ind.donchian_low(df["low"], params.exit_lookback)
        atr = ind.atr(df, params.atr_period)

        entry = spy_ok & (close > sma) & (close > upper)
        reason = describe(
            entry,
            f"{TITLE}: Close {{close:.2f}} > maximul pe {params.entry_lookback} de zile "
            f"{{upper:.2f}}; Close > SMA{params.sma_filter} {{sma:.2f}}; "
            f"SPY > SMA{params.sma_filter}",
            close=close,
            upper=upper,
            sma=sma,
        )
        out[sym] = signal_frame(
            entry=entry,
            exit=close < lower,
            stop_distance=params.stop_atr * atr,
            score=(close - upper) / atr,  # breakout strength in ATRs ranks same-day entries
            entry_reason=reason,
        )
    return out
