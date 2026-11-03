"""Strategy runner and walk-forward evaluation (only the out-of-sample aggregate is reported).

Each test window starts flat with the initial capital and closes everything on its last bar.
The OOS equity curve chains the daily returns of the test windows. Indicators are computed on the
full history before each window (causal, checked by the look-ahead detector), so there is no
warm-up gap at the start of a window.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass

import numpy as np
import pandas as pd

from src.backtest.engine import BacktestConfig, BacktestResult, run_backtest
from src.backtest.lookahead import Strategy, assert_no_lookahead
from src.backtest.metrics import daily_returns, equity_metrics, trade_metrics
from src.backtest.panel import MarketPanel, SignalPanel

Calibrator = Callable[[Mapping[str, pd.DataFrame]], Strategy]


def build_panels(
    strategy: Strategy, prices: Mapping[str, pd.DataFrame]
) -> tuple[MarketPanel, SignalPanel]:
    """Run the strategy and align prices and signals of the symbols it trades."""
    signals = strategy(prices)
    panel = MarketPanel.from_frames({sym: prices[sym] for sym in signals})
    return panel, SignalPanel.from_frames(signals, panel)


def backtest_strategy(
    strategy: Strategy,
    prices: Mapping[str, pd.DataFrame],
    config: BacktestConfig | None = None,
    sectors: Mapping[str, str] | None = None,
    start=None,
    end=None,
    check_lookahead: bool = True,
) -> BacktestResult:
    """Look-ahead check, then a single backtest of the strategy."""
    if check_lookahead:
        assert_no_lookahead(strategy, prices)
    panel, signals = build_panels(strategy, prices)
    return run_backtest(panel, signals, config, sectors, start, end)


def make_windows(
    dates: pd.DatetimeIndex, train_years: int = 3, test_years: int = 1
) -> list[tuple[pd.Timestamp, pd.Timestamp]]:
    """Rolling test windows (first bar, last bar), each preceded by `train_years` of history.
    The last window may be shorter (it ends at the last available bar)."""
    windows = []
    start = dates[0] + pd.DateOffset(years=train_years)
    while start <= dates[-1]:
        stop = start + pd.DateOffset(years=test_years)
        in_window = dates[(dates >= start) & (dates < stop)]
        if len(in_window):
            windows.append((in_window[0], in_window[-1]))
        start = stop
    return windows


@dataclass
class WalkForwardResult:
    equity: pd.Series  # chained OOS equity
    trades: pd.DataFrame  # OOS trades only
    exposure: pd.Series
    windows: pd.DataFrame  # per test window: start, end, return, n_trades
    summary: dict


def walk_forward(
    strategy: Strategy,
    prices: Mapping[str, pd.DataFrame],
    config: BacktestConfig | None = None,
    sectors: Mapping[str, str] | None = None,
    train_years: int = 3,
    test_years: int = 1,
    calibrate: Calibrator | None = None,
    check_lookahead: bool = True,
) -> WalkForwardResult:
    """Walk-forward test. `calibrate` (optional) sees only the training data before each window
    and returns the strategy to use in it; without it the same strategy runs in every window."""
    config = config or BacktestConfig()
    if check_lookahead:
        assert_no_lookahead(strategy, prices)
    base_panel, base_signals = build_panels(strategy, prices)
    windows = make_windows(base_panel.dates, train_years, test_years)
    if not windows:
        raise ValueError("History too short for one walk-forward window")

    returns, trades, exposure, rows = [], [], [], []
    for test_start, test_end in windows:
        if calibrate is None:
            panel, signals = base_panel, base_signals
        else:
            train = {sym: df.loc[: test_start - pd.Timedelta(days=1)] for sym, df in prices.items()}
            upto_end = {sym: df.loc[:test_end] for sym, df in prices.items()}
            panel, signals = build_panels(calibrate(train), upto_end)
        result = run_backtest(panel, signals, config, sectors, test_start, test_end)
        returns.append(daily_returns(result.equity, config.initial_capital))
        trades.append(result.trades)
        exposure.append(result.exposure)
        rows.append(
            {
                "test_start": test_start,
                "test_end": test_end,
                "return": result.equity.iloc[-1] / config.initial_capital - 1.0,
                "n_trades": len(result.trades),
            }
        )

    oos_returns = pd.concat(returns)
    equity = (config.initial_capital * (1.0 + oos_returns).cumprod()).rename("equity")
    all_trades = pd.concat([t for t in trades if len(t)] or trades, ignore_index=True)
    all_exposure = pd.concat(exposure)
    window_table = pd.DataFrame(rows)
    summary = {
        **equity_metrics(equity, config.initial_capital),
        **trade_metrics(all_trades),
        "avg_exposure": float(all_exposure.mean()),
        "n_windows": len(window_table),
        "windows_profitable_pct": float(np.mean(window_table["return"] > 0)),
    }
    return WalkForwardResult(equity, all_trades, all_exposure, window_table, summary)
