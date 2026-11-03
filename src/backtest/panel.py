"""Aligned numpy panels (days x symbols) of prices and strategy signals for the engine.

Signal contract: a strategy returns one DataFrame per tradeable symbol, indexed by date, computed
only from bars <= t (checked by src/backtest/lookahead.py). Columns:
- entry (bool, required): buy at the next bar's Open.
- stop_distance (float, required): stop = entry fill - stop_distance. Must be defined on every
  bar where an entry could happen (e.g. 2.5*ATR), so the random-entry test can reuse it.
- exit (bool): sell at the next bar's Open.
- target_distance (float): target = entry fill + target_distance; NaN = no target.
- score (float): ranks entries on the same bar, higher first.
- entry_reason (str): why the entry fired (rule and indicator values), copied to the trade log.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

import numpy as np
import pandas as pd

PRICE_COLUMNS = ("open", "high", "low", "close")
SIGNAL_COLUMNS = ("entry", "exit", "stop_distance", "target_distance", "score")


@dataclass(frozen=True)
class MarketPanel:
    dates: pd.DatetimeIndex
    symbols: tuple[str, ...]
    open: np.ndarray
    high: np.ndarray
    low: np.ndarray
    close: np.ndarray
    last_valid: np.ndarray  # last row with a close, per symbol (-1 if none)

    @classmethod
    def from_frames(cls, prices: Mapping[str, pd.DataFrame]) -> MarketPanel:
        """Align OHLC frames on the union of their dates; missing bars are NaN."""
        symbols = tuple(sorted(prices))
        if not symbols:
            raise ValueError("No price data")
        dates = pd.DatetimeIndex(sorted(set().union(*(prices[s].index for s in symbols))))
        arrays = {
            col: np.column_stack(
                [prices[s][col].reindex(dates).to_numpy(dtype=float) for s in symbols]
            )
            for col in PRICE_COLUMNS
        }
        has_close = ~np.isnan(arrays["close"])
        last_valid = np.where(
            has_close.any(axis=0), len(dates) - 1 - np.argmax(has_close[::-1], axis=0), -1
        )
        return cls(dates=dates, symbols=symbols, last_valid=last_valid, **arrays)

    def index_range(self, start=None, end=None) -> tuple[int, int]:
        """Inclusive row range [i0, i1] of the bars between start and end."""
        i0 = 0 if start is None else int(self.dates.searchsorted(pd.Timestamp(start), "left"))
        i1 = (
            len(self.dates) - 1
            if end is None
            else int(self.dates.searchsorted(pd.Timestamp(end), "right")) - 1
        )
        if i0 > i1:
            raise ValueError(f"Empty backtest window: {start} .. {end}")
        return i0, i1


@dataclass(frozen=True)
class SignalPanel:
    entry: np.ndarray
    exit: np.ndarray
    stop_distance: np.ndarray
    target_distance: np.ndarray
    score: np.ndarray
    entry_reason: np.ndarray | None = None

    @classmethod
    def from_frames(cls, signals: Mapping[str, pd.DataFrame], panel: MarketPanel) -> SignalPanel:
        """Align per-symbol signal frames to the panel; symbols without signals never trade."""
        missing = [s for s in signals if s not in panel.symbols]
        if missing:
            raise ValueError(f"Signals for symbols without prices: {missing}")
        for sym, frame in signals.items():
            for col in ("entry", "stop_distance"):
                if col not in frame.columns:
                    raise ValueError(f"[{sym}] signal column '{col}' is required")

        def column(name: str, fill, dtype) -> np.ndarray:
            cols = []
            for sym in panel.symbols:
                frame = signals.get(sym)
                if frame is None or name not in frame.columns:
                    cols.append(np.full(len(panel.dates), fill, dtype=dtype))
                else:
                    series = frame[name].reindex(panel.dates)
                    cols.append(series.where(series.notna(), fill).to_numpy(dtype=dtype))
            return np.column_stack(cols)

        has_reason = any("entry_reason" in f.columns for f in signals.values())
        return cls(
            entry=column("entry", False, bool),
            exit=column("exit", False, bool),
            stop_distance=column("stop_distance", np.nan, float),
            target_distance=column("target_distance", np.nan, float),
            score=column("score", np.nan, float),
            entry_reason=column("entry_reason", "", object) if has_reason else None,
        )
