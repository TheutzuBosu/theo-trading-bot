"""Market timing utilities (New York exchange hours and bar completion)."""

from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo

import pandas as pd

NY_TZ = ZoneInfo("America/New_York")
MARKET_CLOSE_TIME = dt.time(16, 0)


def get_current_ny_time() -> dt.datetime:
    """Return the current time in America/New_York timezone."""
    return dt.datetime.now(NY_TZ)


def is_ny_market_closed(current_time: dt.datetime | None = None) -> bool:
    """Check if the regular NYSE/NASDAQ market has closed for the day.

    Regular trading hours end at 16:00 (4:00 PM) Eastern Time.
    """
    now = current_time or get_current_ny_time()
    if now.tzinfo is None:
        now = now.replace(tzinfo=NY_TZ)
    else:
        now = now.astimezone(NY_TZ)

    return now.time() >= MARKET_CLOSE_TIME


def drop_incomplete_bar(
    df: pd.DataFrame,
    current_time: dt.datetime | None = None,
) -> pd.DataFrame:
    """Drop the current day's bar if the New York market has not closed yet.

    If the last row in df corresponds to today's date in New York time, and
    current time is before 16:00 NY, that bar is still forming and must be dropped
    to prevent lookahead bias. Any rows dated after today are also dropped.

    Args:
        df: DataFrame with DatetimeIndex of daily bars.
        current_time: Optional datetime (defaults to current time in NY).

    Returns:
        DataFrame with incomplete/future bars removed.
    """
    if df is None or df.empty:
        return df

    now_ny = current_time or get_current_ny_time()
    if now_ny.tzinfo is None:
        now_ny = now_ny.replace(tzinfo=NY_TZ)
    else:
        now_ny = now_ny.astimezone(NY_TZ)

    ny_today = now_ny.date()
    market_closed = now_ny.time() >= MARKET_CLOSE_TIME

    # Convert index dates to date objects in NY timezone
    if isinstance(df.index, pd.DatetimeIndex):
        if df.index.tz is None:
            # Naive timestamps represent local trading dates
            idx_dates = pd.Series([ts.date() for ts in df.index], index=df.index)
        else:
            idx_dates = pd.Series([ts.astimezone(NY_TZ).date() for ts in df.index], index=df.index)
    else:
        # Non-datetime index, cannot filter by time
        return df

    # Drop any bar beyond today
    valid_mask = idx_dates <= ny_today

    # If market is not closed yet, drop today's bar as well
    if not market_closed:
        valid_mask = valid_mask & (idx_dates < ny_today)

    return df.loc[valid_mask].copy()
