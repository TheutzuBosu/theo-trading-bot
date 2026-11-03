"""Monte Carlo on the trade list and the random-entry test."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace

import numpy as np
import pandas as pd

from src.backtest.engine import BacktestConfig, run_backtest
from src.backtest.metrics import summarize
from src.backtest.panel import MarketPanel, SignalPanel

PERCENTILES = (5, 25, 50, 75, 95)


def trade_returns(trades: pd.DataFrame) -> np.ndarray:
    """Each trade's P&L as a fraction of the bot equity when it was opened."""
    return (trades["pnl"] / trades["equity_at_entry"]).to_numpy(dtype=float)


def _path_stats(rets: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Max drawdown and total return of each row of compounded trade returns."""
    paths = np.cumprod(1.0 + rets, axis=1)
    paths = np.hstack([np.ones((rets.shape[0], 1)), paths])
    peaks = np.maximum.accumulate(paths, axis=1)
    return np.max(1.0 - paths / peaks, axis=1), paths[:, -1] - 1.0


@dataclass
class MonteCarloResult:
    drawdowns: np.ndarray  # max DD of each reshuffled order of the trades
    returns: np.ndarray  # total return of each bootstrap resample
    bootstrap_drawdowns: np.ndarray

    def summary(self) -> dict:
        out = {"n_runs": len(self.drawdowns)}
        for p in PERCENTILES:
            out[f"drawdown_p{p}"] = float(np.percentile(self.drawdowns, p))
            out[f"return_p{p}"] = float(np.percentile(self.returns, p))
        return out


def monte_carlo(
    trades: pd.DataFrame, n_runs: int = 1000, seed: int = 42, n_trades: int | None = None
) -> MonteCarloResult:
    """Drawdown distribution from `n_runs` reshuffles of the trade order. A reshuffle never
    changes the final return, so the return distribution comes from `n_runs` bootstrap resamples
    (with replacement) of `n_trades` trades (default: as many as in the backtest)."""
    rets = trade_returns(trades)
    if rets.size == 0:
        raise ValueError("Monte Carlo needs at least one trade")
    rng = np.random.default_rng(seed)
    shuffled = np.vstack([rng.permutation(rets) for _ in range(n_runs)])
    drawdowns, _ = _path_stats(shuffled)
    sampled = rng.choice(rets, size=(n_runs, n_trades or rets.size), replace=True)
    boot_dd, boot_ret = _path_stats(sampled)
    return MonteCarloResult(drawdowns=drawdowns, returns=boot_ret, bootstrap_drawdowns=boot_dd)


RANDOM_METRICS = ("total_return", "sharpe", "profit_factor", "expectancy_r")


@dataclass
class RandomEntryResult:
    strategy: dict  # metrics of the real strategy
    random: pd.DataFrame  # one row of metrics per random run
    beats: dict  # per metric: fraction of random runs the strategy beats


def random_entry_test(
    panel: MarketPanel,
    signals: SignalPanel,
    config: BacktestConfig | None = None,
    sectors: Mapping[str, str] | None = None,
    n_runs: int = 500,
    seed: int = 42,
    start=None,
    end=None,
) -> RandomEntryResult:
    """Replace the entries with random ones (same count per symbol, random bars and ranking),
    keeping exits, stops, targets and sizing; compare the strategy with every random run."""
    config = config or BacktestConfig()
    base = summarize(run_backtest(panel, signals, config, sectors, start, end))
    quiet = replace(config, record_rejections=False)

    i0, i1 = panel.index_range(start, end)
    window = np.zeros(len(panel.dates), dtype=bool)
    window[i0:i1] = True  # a signal on the last bar never executes
    eligible = (
        window[:, None]
        & np.isfinite(panel.close)
        & np.isfinite(signals.stop_distance)
        & (signals.stop_distance > 0)
    )
    counts = (signals.entry & eligible).sum(axis=0)
    rows_by_symbol = [np.flatnonzero(eligible[:, j]) for j in range(len(panel.symbols))]

    rng = np.random.default_rng(seed)
    runs = []
    for _ in range(n_runs):
        entry = np.zeros_like(signals.entry)
        for j, k in enumerate(counts):
            if k:
                entry[rng.choice(rows_by_symbol[j], size=k, replace=False), j] = True
        randomized = replace(signals, entry=entry, score=rng.random(entry.shape))
        metrics = summarize(run_backtest(panel, randomized, quiet, sectors, start, end))
        runs.append({m: metrics[m] for m in RANDOM_METRICS})

    random = pd.DataFrame(runs, columns=list(RANDOM_METRICS))
    beats = {}
    for m in RANDOM_METRICS:
        values = random[m].to_numpy(dtype=float)
        # a random run without a value (e.g. no trades) counts as beaten
        if np.isnan(base[m]):
            beats[m] = 0.0
        else:
            beats[m] = float(np.mean(np.where(np.isnan(values), True, base[m] > values)))
    return RandomEntryResult(strategy=base, random=random, beats=beats)
