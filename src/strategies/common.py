"""Helpers shared by the strategies (pure functions of closed bars)."""

from __future__ import annotations

from collections.abc import Mapping

import numpy as np
import pandas as pd
from pydantic import BaseModel, ConfigDict

from src import indicators as ind
from src.data.universe import BENCHMARK_SYMBOL


class StrategyParams(BaseModel):
    """Base for strategy parameters: every field is required and unknown keys are refused."""

    model_config = ConfigDict(extra="forbid", frozen=True)


def split_benchmark(
    prices: Mapping[str, pd.DataFrame],
) -> tuple[dict[str, pd.DataFrame], pd.DataFrame | None]:
    """Tradeable symbols and the SPY frame (None if absent)."""
    stocks = {s: df for s, df in prices.items() if s != BENCHMARK_SYMBOL}
    return stocks, prices.get(BENCHMARK_SYMBOL)


def benchmark_uptrend(spy: pd.DataFrame | None, index: pd.Index, n: int) -> pd.Series:
    """SPY Close > SMA(n), aligned to `index`; False where SPY has no bar."""
    if spy is None:
        raise ValueError(f"{BENCHMARK_SYMBOL} prices are required for the market filter")
    ok = spy["close"] > ind.sma(spy["close"], n)
    return ok.reindex(index).fillna(False).astype(bool)


def describe(entry: pd.Series, template: str, **values: pd.Series) -> pd.Series:
    """Text reason on entry bars (template filled with the indicator values), '' elsewhere."""
    out = pd.Series("", index=entry.index, dtype=object)
    rows = np.flatnonzero(entry.to_numpy(dtype=bool))
    if len(rows):
        cols = {k: v.to_numpy(dtype=float)[rows] for k, v in values.items()}
        out.iloc[rows] = [
            template.format(**{k: c[i] for k, c in cols.items()}) for i in range(len(rows))
        ]
    return out


def signal_frame(
    entry: pd.Series,
    exit: pd.Series,
    stop_distance: pd.Series,
    score: pd.Series,
    entry_reason: pd.Series,
    target_distance: pd.Series | None = None,
) -> pd.DataFrame:
    """Frame in the signal contract of src/backtest/panel.py."""
    return pd.DataFrame(
        {
            "entry": entry.fillna(False).astype(bool),
            "exit": exit.fillna(False).astype(bool),
            "stop_distance": stop_distance.astype(float),
            "target_distance": np.nan if target_distance is None else target_distance.astype(float),
            "score": score.astype(float),
            "entry_reason": entry_reason,
        },
        index=entry.index,
    )
