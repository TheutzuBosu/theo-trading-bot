"""Technical indicators in pure pandas (no TA-Lib).

All indicators are causal: the value at bar t uses only bars <= t. Wilder-smoothed indicators
(ATR, RSI, ADX) and EMA are seeded with the simple mean of their first n valid values.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def _seeded_ewm(series: pd.Series, n: int, alpha: float) -> pd.Series:
    """Recursive smoothing y[t] = alpha*x[t] + (1-alpha)*y[t-1], seeded with the mean of the
    first n valid values. Leading NaNs are skipped; the result is NaN until the seed bar."""
    values = series.astype(float)
    out = pd.Series(np.nan, index=series.index, dtype=float)
    valid_pos = np.flatnonzero(values.notna().to_numpy())
    if len(valid_pos) < n:
        return out
    seed_pos = valid_pos[n - 1]
    tail = values.iloc[seed_pos:].copy()
    tail.iloc[0] = values.iloc[valid_pos[:n]].mean()
    out.iloc[seed_pos:] = tail.ewm(alpha=alpha, adjust=False).mean().to_numpy()
    return out


def wilder(series: pd.Series, n: int) -> pd.Series:
    """Wilder smoothing (alpha = 1/n), seeded with the mean of the first n values."""
    return _seeded_ewm(series, n, 1.0 / n)


def sma(series: pd.Series, n: int) -> pd.Series:
    """Simple moving average over the last n bars."""
    return series.astype(float).rolling(n, min_periods=n).mean()


def ema(series: pd.Series, n: int) -> pd.Series:
    """Exponential moving average (alpha = 2/(n+1)), seeded with the SMA of the first n bars."""
    return _seeded_ewm(series, n, 2.0 / (n + 1))


def true_range(df: pd.DataFrame) -> pd.Series:
    """True range; the first bar (no previous close) uses high - low."""
    prev_close = df["close"].shift(1)
    ranges = pd.concat(
        [
            df["high"] - df["low"],
            (df["high"] - prev_close).abs(),
            (df["low"] - prev_close).abs(),
        ],
        axis=1,
    )
    return ranges.max(axis=1, skipna=True)


def atr(df: pd.DataFrame, n: int = 20) -> pd.Series:
    """Average true range, Wilder smoothing."""
    return wilder(true_range(df), n)


def rsi(close: pd.Series, n: int = 14) -> pd.Series:
    """Relative strength index, Wilder smoothing. Flat window -> 50, no losses -> 100."""
    delta = close.astype(float).diff()
    avg_gain = wilder(delta.clip(lower=0.0), n)
    avg_loss = wilder(-delta.clip(upper=0.0), n)
    out = 100.0 - 100.0 / (1.0 + avg_gain / avg_loss)
    out = out.where(avg_loss > 0, 100.0)
    out = out.where(~((avg_gain == 0) & (avg_loss == 0)), 50.0)
    return out.where(avg_gain.notna() & avg_loss.notna())


def donchian_high(high: pd.Series, n: int) -> pd.Series:
    """Highest high of the previous n bars, excluding the current bar (shifted by 1)."""
    return high.astype(float).rolling(n, min_periods=n).max().shift(1)


def donchian_low(low: pd.Series, n: int) -> pd.Series:
    """Lowest low of the previous n bars, excluding the current bar (shifted by 1)."""
    return low.astype(float).rolling(n, min_periods=n).min().shift(1)


def adx(df: pd.DataFrame, n: int = 14) -> pd.Series:
    """Average directional index (Wilder). DM and TR start at bar 1 (they need a previous bar)."""
    up = df["high"].diff()
    down = -df["low"].diff()
    plus_dm = up.where((up > down) & (up > 0), 0.0).where(up.notna())
    minus_dm = down.where((down > up) & (down > 0), 0.0).where(down.notna())
    tr = true_range(df).where(df["close"].shift(1).notna())

    atr_s = wilder(tr, n)
    plus_di = 100.0 * wilder(plus_dm, n) / atr_s
    minus_di = 100.0 * wilder(minus_dm, n) / atr_s
    di_sum = plus_di + minus_di
    dx = (100.0 * (plus_di - minus_di).abs() / di_sum).where(di_sum > 0, 0.0)
    return wilder(dx.where(plus_di.notna()), n)


def momentum_12_1(close: pd.Series, lookback: int = 252, skip: int = 21) -> pd.Series:
    """12-1 month return: from `lookback` bars ago to `skip` bars ago (skips the last month)."""
    close = close.astype(float)
    return close.shift(skip) / close.shift(lookback) - 1.0
