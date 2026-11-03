"""Builders for synthetic prices and signals used by the backtest tests."""

import numpy as np
import pandas as pd

from src.backtest.panel import MarketPanel, SignalPanel


def bars(rows, start="2026-01-05") -> pd.DataFrame:
    """rows of (open, high, low, close) -> OHLCV frame on business days."""
    df = pd.DataFrame(rows, columns=["open", "high", "low", "close"], dtype=float)
    df.index = pd.date_range(start, periods=len(df), freq="B")
    df["volume"] = 1_000_000.0
    return df


def signal_frame(index, entries=(), exits=(), stop=10.0, target=np.nan, score=np.nan):
    """Signals with entries/exits on the given row numbers and constant distances."""
    frame = pd.DataFrame(
        {
            "entry": False,
            "exit": False,
            "stop_distance": stop,
            "target_distance": target,
            "score": score,
        },
        index=index,
    )
    frame.iloc[list(entries), frame.columns.get_loc("entry")] = True
    frame.iloc[list(exits), frame.columns.get_loc("exit")] = True
    return frame


def panels(prices: dict, signals: dict) -> tuple[MarketPanel, SignalPanel]:
    panel = MarketPanel.from_frames(prices)
    return panel, SignalPanel.from_frames(signals, panel)


def random_walk(n: int, seed: int, start="2015-01-02", drift=0.0003, vol=0.015) -> pd.DataFrame:
    """Plausible daily OHLC bars from a seeded random walk."""
    rng = np.random.default_rng(seed)
    close = 100.0 * np.exp(np.cumsum(rng.normal(drift, vol, n)))
    open_ = np.concatenate([[100.0], close[:-1]]) * np.exp(rng.normal(0, vol / 3, n))
    high = np.maximum(open_, close) * (1 + np.abs(rng.normal(0, vol / 2, n)))
    low = np.minimum(open_, close) * (1 - np.abs(rng.normal(0, vol / 2, n)))
    df = pd.DataFrame({"open": open_, "high": high, "low": low, "close": close})
    df.index = pd.bdate_range(start, periods=n)
    df["volume"] = 1_000_000.0
    return df
