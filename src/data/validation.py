"""Data validation module for market OHLCV bars."""

from __future__ import annotations

import pandas as pd


class DataValidationError(ValueError):
    """Raised when market data fails validation checks."""

    pass


REQUIRED_COLUMNS = ["open", "high", "low", "close", "volume"]
# OHLC differences below this relative size are float rounding from the yfinance dividend/split
# adjustment (e.g. high=28.8222541809082 vs close=28.822254180908203), not bad data.
PRICE_RTOL = 1e-9


def _below(df: pd.DataFrame, a: str, b: str) -> pd.DataFrame:
    """Rows where column `a` is below column `b` by more than the rounding tolerance."""
    return df[df[a] < df[b] * (1.0 - PRICE_RTOL)]


def validate(
    df: pd.DataFrame,
    symbol: str | None = None,
    max_gap_days: int = 7,
    max_price_ratio_jump: float = 5.0,
) -> None:
    """Validate daily OHLCV market data.

    Checks:
    - Required columns exist ('open', 'high', 'low', 'close', 'volume')
    - DataFrame is not empty
    - Index is DatetimeIndex and strictly monotonic increasing
    - No duplicate dates
    - No NaN / null values in required columns
    - All prices (open, high, low, close) > 0
    - Volume >= 0
    - High is highest and Low is lowest:
      high >= low, high >= open, high >= close, low <= open, low <= close
    - No abnormal calendar gaps (> max_gap_days)
    - No abnormal price jumps (> max_price_ratio_jump or < 1/max_price_ratio_jump)

    Raises:
        DataValidationError: If any validation rule is violated, with a detailed description.
    """
    prefix = f"[{symbol}] " if symbol else ""

    if df is None or df.empty:
        raise DataValidationError(f"{prefix}DataFrame is empty or None")

    # Column existence
    missing_cols = [col for col in REQUIRED_COLUMNS if col not in df.columns]
    if missing_cols:
        raise DataValidationError(
            f"{prefix}Missing required columns: {missing_cols}. Present columns: {list(df.columns)}"
        )

    # Check index
    if not isinstance(df.index, pd.DatetimeIndex):
        raise DataValidationError(
            f"{prefix}DataFrame index must be a DatetimeIndex, got {type(df.index)}"
        )

    # Duplicate dates
    duplicates = df.index[df.index.duplicated()].unique()
    if len(duplicates) > 0:
        dup_str = ", ".join(d.strftime("%Y-%m-%d") for d in duplicates[:5])
        raise DataValidationError(
            f"{prefix}Found {len(duplicates)} duplicate date(s) in index: {dup_str}"
        )

    # Monotonic increasing
    if not df.index.is_monotonic_increasing:
        raise DataValidationError(f"{prefix}Dates in index are not strictly monotonic increasing")

    # NaN / Null check
    nan_counts = df[REQUIRED_COLUMNS].isna().sum()
    cols_with_nans = nan_counts[nan_counts > 0]
    if not cols_with_nans.empty:
        details = ", ".join(f"{col}: {cnt}" for col, cnt in cols_with_nans.items())
        first_nan_row = df[df[REQUIRED_COLUMNS].isna().any(axis=1)].index[0]
        first_date = first_nan_row.strftime("%Y-%m-%d")
        raise DataValidationError(
            f"{prefix}NaN values found ({details}). First occurrence at date {first_date}"
        )

    # Prices <= 0
    for col in ["open", "high", "low", "close"]:
        non_positive = df[df[col] <= 0]
        if not non_positive.empty:
            bad_date = non_positive.index[0].strftime("%Y-%m-%d")
            bad_val = non_positive[col].iloc[0]
            raise DataValidationError(
                f"{prefix}Non-positive price found in column '{col}': value {bad_val} on {bad_date}"
            )

    # Volume < 0
    negative_vol = df[df["volume"] < 0]
    if not negative_vol.empty:
        bad_date = negative_vol.index[0].strftime("%Y-%m-%d")
        bad_val = negative_vol["volume"].iloc[0]
        raise DataValidationError(f"{prefix}Negative volume found: value {bad_val} on {bad_date}")

    # High / Low price consistency
    bad_hl = _below(df, "high", "low")
    if not bad_hl.empty:
        d = bad_hl.index[0].strftime("%Y-%m-%d")
        h_val = bad_hl["high"].iloc[0]
        l_val = bad_hl["low"].iloc[0]
        raise DataValidationError(f"{prefix}High < Low on {d}: high={h_val}, low={l_val}")

    bad_ho = _below(df, "high", "open")
    if not bad_ho.empty:
        d = bad_ho.index[0].strftime("%Y-%m-%d")
        h_val = bad_ho["high"].iloc[0]
        o_val = bad_ho["open"].iloc[0]
        raise DataValidationError(f"{prefix}High < Open on {d}: high={h_val}, open={o_val}")

    bad_hc = _below(df, "high", "close")
    if not bad_hc.empty:
        d = bad_hc.index[0].strftime("%Y-%m-%d")
        h_val = bad_hc["high"].iloc[0]
        c_val = bad_hc["close"].iloc[0]
        raise DataValidationError(f"{prefix}High < Close on {d}: high={h_val}, close={c_val}")

    bad_lo = _below(df, "open", "low")
    if not bad_lo.empty:
        d = bad_lo.index[0].strftime("%Y-%m-%d")
        l_val = bad_lo["low"].iloc[0]
        o_val = bad_lo["open"].iloc[0]
        raise DataValidationError(f"{prefix}Low > Open on {d}: low={l_val}, open={o_val}")

    bad_lc = _below(df, "close", "low")
    if not bad_lc.empty:
        d = bad_lc.index[0].strftime("%Y-%m-%d")
        l_val = bad_lc["low"].iloc[0]
        c_val = bad_lc["close"].iloc[0]
        raise DataValidationError(f"{prefix}Low > Close on {d}: low={l_val}, close={c_val}")

    # Abnormal calendar gaps
    if len(df) > 1:
        dates = pd.Series(df.index.normalize(), index=df.index)
        diffs = dates.diff().dt.days
        abnormal_gaps = diffs[diffs > max_gap_days]
        if not abnormal_gaps.empty:
            gap_date = abnormal_gaps.index[0]
            gap_days = int(abnormal_gaps.iloc[0])
            prev_idx = df.index.get_loc(gap_date) - 1
            prev_date = df.index[prev_idx].strftime("%Y-%m-%d")
            cur_date = gap_date.strftime("%Y-%m-%d")
            raise DataValidationError(
                f"{prefix}Abnormal calendar gap of {gap_days} days between "
                f"{prev_date} and {cur_date} (max allowed: {max_gap_days})"
            )

        # Abnormal price jumps (e.g. 5x jump or drop to 0.2x from one bar to next)
        if max_price_ratio_jump > 1.0:
            pct_change = df["close"] / df["close"].shift(1)
            lower_bound = 1.0 / max_price_ratio_jump
            bad_jumps = pct_change[(pct_change > max_price_ratio_jump) | (pct_change < lower_bound)]
            if not bad_jumps.empty:
                jump_date = bad_jumps.index[0]
                ratio = float(bad_jumps.iloc[0])
                prev_idx = df.index.get_loc(jump_date) - 1
                prev_p = df["close"].iloc[prev_idx]
                curr_p = df["close"].loc[jump_date]
                j_date_str = jump_date.strftime("%Y-%m-%d")
                raise DataValidationError(
                    f"{prefix}Abnormal price jump on {j_date_str}: "
                    f"previous close={prev_p:.2f}, current close={curr_p:.2f} "
                    f"(ratio={ratio:.2f})"
                )
