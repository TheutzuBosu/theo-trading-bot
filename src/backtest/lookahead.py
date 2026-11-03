"""Look-ahead detector: a strategy run on data cut at day t must give the same signals up to t
as the run on the full history. Any difference means the strategy used bars after t."""

from __future__ import annotations

from collections.abc import Callable, Mapping

import numpy as np
import pandas as pd

from src.backtest.panel import SIGNAL_COLUMNS

Strategy = Callable[[Mapping[str, pd.DataFrame]], Mapping[str, pd.DataFrame]]


class LookAheadError(AssertionError):
    """Raised when a strategy's signals depend on future bars."""


def _same(a: pd.Series, b: pd.Series) -> np.ndarray:
    if a.dtype == bool or b.dtype == bool:
        return a.fillna(False).astype(bool).to_numpy() == b.fillna(False).astype(bool).to_numpy()
    x, y = a.to_numpy(dtype=float), b.to_numpy(dtype=float)
    return np.isclose(x, y, rtol=1e-9, atol=1e-12, equal_nan=True)


def find_lookahead(
    strategy: Strategy,
    prices: Mapping[str, pd.DataFrame],
    n_checks: int = 10,
    min_history: int = 30,
) -> list[str]:
    """Run the strategy on `n_checks` truncated histories; return the mismatches found."""
    full = strategy(prices)
    dates = pd.DatetimeIndex(sorted(set().union(*(df.index for df in prices.values()))))
    if len(dates) <= min_history + 1:
        raise ValueError("Not enough history for the look-ahead check")
    cut_rows = np.unique(np.linspace(min_history, len(dates) - 2, n_checks).astype(int))
    problems: list[str] = []
    for row in cut_rows:
        cutoff = dates[row]
        cut = strategy({sym: df.loc[:cutoff] for sym, df in prices.items()})
        for sym, frame in full.items():
            expected = frame.loc[:cutoff]
            got = cut.get(sym)
            if got is None:
                problems.append(f"{sym}: no signals when the history ends at {cutoff.date()}")
                continue
            got = got.reindex(expected.index)
            for col in SIGNAL_COLUMNS:
                if col not in expected.columns:
                    continue
                if col not in got.columns:
                    problems.append(f"{sym}.{col}: missing when cut at {cutoff.date()}")
                    continue
                diff = ~_same(expected[col], got[col])
                if diff.any():
                    first = expected.index[np.argmax(diff)].date()
                    problems.append(f"{sym}.{col}: differs on {first} (cut at {cutoff.date()})")
    return problems


def assert_no_lookahead(strategy: Strategy, prices: Mapping[str, pd.DataFrame], **kwargs) -> None:
    """Raise LookAheadError if the strategy peeks at future bars."""
    problems = find_lookahead(strategy, prices, **kwargs)
    if problems:
        shown = "; ".join(problems[:5])
        raise LookAheadError(f"Strategy uses future data ({len(problems)} mismatches): {shown}")
