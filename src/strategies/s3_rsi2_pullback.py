"""S3 RSI-2 Pullback. Filter: SPY > SMA200 and Close > SMA200. Entry: RSI(2) < 10.
Exit: Close > SMA(5), or after 10 bars (engine `max_hold_bars`).
Catastrophe stop: entry - 3*ATR(20)."""

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

TITLE = "S3 RSI-2 Pullback"


class Params(StrategyParams):
    sma_filter: int
    rsi_period: int
    rsi_entry: float
    exit_sma: int
    max_hold_bars: int
    atr_period: int
    stop_atr: float


def signals(prices: Mapping[str, pd.DataFrame], params: Params) -> dict[str, pd.DataFrame]:
    stocks, spy = split_benchmark(prices)
    out = {}
    for sym, df in stocks.items():
        close = df["close"]
        spy_ok = benchmark_uptrend(spy, df.index, params.sma_filter)
        sma = ind.sma(close, params.sma_filter)
        rsi = ind.rsi(close, params.rsi_period)

        entry = spy_ok & (close > sma) & (rsi < params.rsi_entry)
        reason = describe(
            entry,
            f"{TITLE}: RSI({params.rsi_period}) {{rsi:.1f}} < {params.rsi_entry:g}; "
            f"Close {{close:.2f}} > SMA{params.sma_filter} {{sma:.2f}}; "
            f"SPY > SMA{params.sma_filter}",
            rsi=rsi,
            close=close,
            sma=sma,
        )
        out[sym] = signal_frame(
            entry=entry,
            exit=close > ind.sma(close, params.exit_sma),
            stop_distance=params.stop_atr * ind.atr(df, params.atr_period),
            score=-rsi,  # the deeper pullback ranks first
            entry_reason=reason,
        )
    return out
