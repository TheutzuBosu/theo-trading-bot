"""S4 MACD + EMA200 (after TradingLab, adapted to daily stocks). Filter: Close > EMA(200).
Entry: the MACD(12,26,9) line crosses above the signal line with both below zero.
Stop: the lower of the 10-day low and Close - 1.5*ATR(20), i.e. at least 1.5*ATR away.
Target: 1.5 x the stop distance. Exit only at the stop or the target. No SPY filter."""

from __future__ import annotations

from collections.abc import Mapping

import pandas as pd

from src import indicators as ind
from src.strategies.common import StrategyParams, describe, signal_frame, split_benchmark

TITLE = "S4 MACD + EMA200"


class Params(StrategyParams):
    ema_filter: int
    macd_fast: int
    macd_slow: int
    macd_signal: int
    swing_lookback: int
    atr_period: int
    min_stop_atr: float
    target_r: float


def signals(prices: Mapping[str, pd.DataFrame], params: Params) -> dict[str, pd.DataFrame]:
    stocks, _ = split_benchmark(prices)
    out = {}
    for sym, df in stocks.items():
        close = df["close"]
        ema = ind.ema(close, params.ema_filter)
        m = ind.macd(close, params.macd_fast, params.macd_slow, params.macd_signal)
        atr = ind.atr(df, params.atr_period)
        n_swing = params.swing_lookback
        swing_low = df["low"].rolling(n_swing, min_periods=n_swing).min()

        cross_up = (m["macd"] > m["signal"]) & (m["macd"].shift(1) <= m["signal"].shift(1))
        entry = (close > ema) & cross_up & (m["macd"] < 0) & (m["signal"] < 0)
        # stop = min(swing low, Close - k*ATR)  ->  distance = max(Close - swing low, k*ATR)
        stop_distance = pd.concat([close - swing_low, params.min_stop_atr * atr], axis=1).max(
            axis=1, skipna=False
        )
        target_distance = params.target_r * stop_distance
        reason = describe(
            entry,
            f"{TITLE}: MACD {{macd:.3f}} taie în sus semnalul {{sig:.3f}}, ambele sub zero; "
            f"Close {{close:.2f}} > EMA{params.ema_filter} {{ema:.2f}}; "
            f"stop cu {{stop:.2f}} sub intrare, țintă cu {{target:.2f}} peste",
            macd=m["macd"],
            sig=m["signal"],
            close=close,
            ema=ema,
            stop=stop_distance,
            target=target_distance,
        )
        out[sym] = signal_frame(
            entry=entry,
            exit=pd.Series(False, index=df.index),
            stop_distance=stop_distance,
            target_distance=target_distance,
            score=m["hist"] / atr,  # strength of the cross in ATRs ranks same-day entries
            entry_reason=reason,
        )
    return out
