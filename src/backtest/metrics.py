"""Performance metrics for strategies and the SPY buy-and-hold benchmark.

Sharpe: daily returns, risk-free rate 0, annualized with sqrt(252). CAGR uses calendar days.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.backtest.engine import BacktestResult, CostModel

TRADING_DAYS = 252


def max_drawdown(values) -> float:
    """Largest peak-to-trough fall as a positive fraction (0.25 = -25%)."""
    arr = np.asarray(values, dtype=float)
    if arr.size == 0:
        return 0.0
    peaks = np.maximum.accumulate(arr)
    return float(np.max(1.0 - arr / peaks))


def daily_returns(equity: pd.Series, initial: float | None = None) -> pd.Series:
    """Bar returns; the first one is measured from `initial` (default: the first value)."""
    base = equity.iloc[0] if initial is None else initial
    prev = equity.shift(1)
    prev.iloc[0] = base
    return equity / prev - 1.0


def equity_metrics(equity: pd.Series, initial: float | None = None) -> dict:
    """Total return, CAGR, Sharpe and max drawdown of an equity curve."""
    base = float(equity.iloc[0] if initial is None else initial)
    total = float(equity.iloc[-1] / base - 1.0)
    years = (equity.index[-1] - equity.index[0]).days / 365.25
    cagr = (1.0 + total) ** (1.0 / years) - 1.0 if years > 0 and total > -1 else np.nan
    rets = daily_returns(equity, base)
    std = rets.std(ddof=1)
    sharpe = float(rets.mean() / std * np.sqrt(TRADING_DAYS)) if std > 0 else np.nan
    return {
        "total_return": total,
        "cagr": float(cagr),
        "sharpe": sharpe,
        "max_drawdown": max_drawdown(np.concatenate([[base], equity.to_numpy(dtype=float)])),
    }


def trade_metrics(trades: pd.DataFrame) -> dict:
    """Number of trades, win rate, profit factor and expectancy in R."""
    n = len(trades)
    if n == 0:
        return {"n_trades": 0, "win_rate": np.nan, "profit_factor": np.nan, "expectancy_r": np.nan}
    pnl = trades["pnl"].to_numpy(dtype=float)
    gains = pnl[pnl > 0].sum()
    losses = -pnl[pnl < 0].sum()
    if losses > 0:
        pf = float(gains / losses)
    else:
        pf = np.inf if gains > 0 else np.nan
    return {
        "n_trades": n,
        "win_rate": float((pnl > 0).mean()),
        "profit_factor": pf,
        "expectancy_r": float(trades["r_multiple"].mean()),
    }


def summarize(result: BacktestResult) -> dict:
    """All metrics of a backtest run."""
    return {
        **equity_metrics(result.equity, result.config.initial_capital),
        **trade_metrics(result.trades),
        "avg_exposure": float(result.exposure.mean()),
    }


def buy_and_hold(
    prices: pd.DataFrame, initial: float, costs: CostModel | None = None, start=None, end=None
) -> pd.Series:
    """Equity of buying at the first Open (with costs) and holding; the last value is net of the
    selling costs, like the strategy that closes everything at the end."""
    costs = costs or CostModel()
    window = prices.loc[start:end]
    if window.empty:
        raise ValueError(f"No benchmark data between {start} and {end}")
    shares = initial / costs.buy_price(float(window["open"].iloc[0]))
    equity = shares * window["close"].astype(float)
    equity.iloc[-1] = shares * costs.sell_price(float(window["close"].iloc[-1]))
    return equity.rename("equity")


def benchmark_summary(
    prices: pd.DataFrame, initial: float, costs: CostModel | None = None, start=None, end=None
) -> dict:
    """Same metrics as `summarize` for SPY buy-and-hold over the same period."""
    equity = buy_and_hold(prices, initial, costs, start, end)
    return {
        **equity_metrics(equity, initial),
        "n_trades": 1,
        "win_rate": np.nan,
        "profit_factor": np.nan,
        "expectancy_r": np.nan,
        "avg_exposure": 1.0,
    }
