"""Tests for New York market hours and drop_incomplete_bar."""

import datetime as dt

import pandas as pd

from src.data.market_time import NY_TZ, drop_incomplete_bar, is_ny_market_closed


def test_is_ny_market_closed():
    # Before 16:00 NY
    before_close = dt.datetime(2026, 11, 3, 15, 59, tzinfo=NY_TZ)
    assert not is_ny_market_closed(before_close)

    # Exactly 16:00 NY
    at_close = dt.datetime(2026, 11, 3, 16, 0, tzinfo=NY_TZ)
    assert is_ny_market_closed(at_close)

    # After 16:00 NY
    after_close = dt.datetime(2026, 11, 3, 16, 30, tzinfo=NY_TZ)
    assert is_ny_market_closed(after_close)


def test_drop_incomplete_bar_midday():
    # Simulated current time: 14:30 on 2026-11-03 (market is open)
    current_time = dt.datetime(2026, 11, 3, 14, 30, tzinfo=NY_TZ)

    # Daily bars up to today (2026-11-03)
    dates = pd.date_range("2026-10-30", "2026-11-03", freq="D")
    df = pd.DataFrame(
        {
            "open": [100.0] * len(dates),
            "high": [105.0] * len(dates),
            "low": [99.0] * len(dates),
            "close": [102.0] * len(dates),
            "volume": [1000.0] * len(dates),
        },
        index=dates,
    )

    filtered = drop_incomplete_bar(df, current_time=current_time)

    # Today's bar must be dropped because market is not closed yet
    assert pd.Timestamp("2026-11-03") not in filtered.index
    assert filtered.index[-1] == pd.Timestamp("2026-11-02")
    assert len(filtered) == len(df) - 1


def test_keep_completed_bar_after_close():
    # Simulated current time: 16:15 on 2026-11-03 (market closed)
    current_time = dt.datetime(2026, 11, 3, 16, 15, tzinfo=NY_TZ)

    dates = pd.date_range("2026-10-30", "2026-11-03", freq="D")
    df = pd.DataFrame(
        {
            "open": [100.0] * len(dates),
            "high": [105.0] * len(dates),
            "low": [99.0] * len(dates),
            "close": [102.0] * len(dates),
            "volume": [1000.0] * len(dates),
        },
        index=dates,
    )

    filtered = drop_incomplete_bar(df, current_time=current_time)

    # Today's bar must be kept because market is closed
    assert pd.Timestamp("2026-11-03") in filtered.index
    assert filtered.index[-1] == pd.Timestamp("2026-11-03")
    assert len(filtered) == len(df)


def test_drop_incomplete_bar_past_data_only():
    # Data ends yesterday (2026-11-02), current time is midday 2026-11-03
    current_time = dt.datetime(2026, 11, 3, 11, 0, tzinfo=NY_TZ)
    dates = pd.date_range("2026-10-25", "2026-11-02", freq="D")
    df = pd.DataFrame(
        {
            "open": [100.0] * len(dates),
            "high": [105.0] * len(dates),
            "low": [99.0] * len(dates),
            "close": [102.0] * len(dates),
            "volume": [1000.0] * len(dates),
        },
        index=dates,
    )

    filtered = drop_incomplete_bar(df, current_time=current_time)
    assert len(filtered) == len(df)
    assert filtered.index[-1] == pd.Timestamp("2026-11-02")


def test_drop_future_bars():
    # Data contains tomorrow (2026-11-04) by mistake
    current_time = dt.datetime(2026, 11, 3, 18, 0, tzinfo=NY_TZ)
    dates = pd.date_range("2026-11-01", "2026-11-04", freq="D")
    df = pd.DataFrame(
        {
            "open": [100.0] * len(dates),
            "high": [105.0] * len(dates),
            "low": [99.0] * len(dates),
            "close": [102.0] * len(dates),
            "volume": [1000.0] * len(dates),
        },
        index=dates,
    )

    filtered = drop_incomplete_bar(df, current_time=current_time)
    assert pd.Timestamp("2026-11-04") not in filtered.index
    assert filtered.index[-1] == pd.Timestamp("2026-11-03")
