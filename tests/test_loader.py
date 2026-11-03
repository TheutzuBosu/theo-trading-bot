"""Tests for data loaders (load_daily and load_recent).

All tests run completely offline without internet calls, using cache and mocks.
"""

from unittest.mock import MagicMock

import pandas as pd
import pytest

from src.data.cache import save_to_cache
from src.data.loader import load_daily, load_recent


@pytest.fixture
def sample_df() -> pd.DataFrame:
    dates = pd.date_range("2026-01-05", periods=5, freq="B")
    return pd.DataFrame(
        {
            "open": [100.0, 102.0, 101.0, 103.0, 105.0],
            "high": [103.0, 104.0, 103.0, 106.0, 107.0],
            "low": [99.0, 101.0, 100.0, 102.0, 104.0],
            "close": [102.0, 101.5, 102.5, 105.0, 106.0],
            "volume": [1000000.0, 1200000.0, 900000.0, 1100000.0, 1300000.0],
        },
        index=dates,
    )


def test_load_daily_from_cache(sample_df, tmp_path):
    symbol = "AAPL"
    save_to_cache(symbol, sample_df, format="parquet", custom_dir=tmp_path)

    df = load_daily(symbol, use_cache=True, cache_dir=tmp_path)
    assert df is not None
    assert len(df) == 5
    assert list(df.columns) == ["open", "high", "low", "close", "volume"]
    assert df["close"].iloc[0] == 102.0


def test_load_daily_with_mocked_yfinance(sample_df, tmp_path, mocker):
    symbol = "MSFT"

    # Raw yfinance style DataFrame (uppercase columns, tz-aware index)
    raw_yf = sample_df.rename(
        columns={"open": "Open", "high": "High", "low": "Low", "close": "Close", "volume": "Volume"}
    ).copy()
    raw_yf.index = raw_yf.index.tz_localize("America/New_York")

    mock_ticker = MagicMock()
    mock_ticker.history.return_value = raw_yf
    mocker.patch("yfinance.Ticker", return_value=mock_ticker)

    df = load_daily(symbol, use_cache=True, cache_dir=tmp_path)
    mock_ticker.history.assert_called_once()
    assert df is not None
    assert len(df) == 5
    assert list(df.columns) == ["open", "high", "low", "close", "volume"]

    # Verify that it was saved to cache
    cached_df = load_daily(symbol, use_cache=True, cache_dir=tmp_path)
    assert len(cached_df) == 5


def test_load_daily_asks_yfinance_for_dashed_class_shares(sample_df, tmp_path, mocker):
    mock_ticker = MagicMock()
    mock_ticker.history.return_value = sample_df
    ticker = mocker.patch("yfinance.Ticker", return_value=mock_ticker)

    df = load_daily("BRK.B", use_cache=True, cache_dir=tmp_path)
    ticker.assert_called_once_with("BRK-B")
    assert len(df) == 5
    # cached under the Alpaca symbol
    assert len(load_daily("BRK.B", use_cache=True, cache_dir=tmp_path)) == 5


def test_load_daily_multi_symbol(sample_df, tmp_path):
    save_to_cache("AAPL", sample_df, format="parquet", custom_dir=tmp_path)
    save_to_cache("MSFT", sample_df, format="parquet", custom_dir=tmp_path)

    results = load_daily(["AAPL", "MSFT"], use_cache=True, cache_dir=tmp_path)
    assert isinstance(results, dict)
    assert "AAPL" in results
    assert "MSFT" in results
    assert len(results["AAPL"]) == 5
    assert len(results["MSFT"]) == 5


def test_load_recent_with_mocked_alpaca(sample_df, tmp_path):
    symbol = "NVDA"

    # MultiIndex DataFrame returned by Alpaca Market Data client
    multi_index = pd.MultiIndex.from_tuples(
        [(symbol, ts) for ts in sample_df.index],
        names=["symbol", "timestamp"],
    )
    alpaca_df = sample_df.copy()
    alpaca_df.index = multi_index

    mock_bars = MagicMock()
    mock_bars.df = alpaca_df

    mock_client = MagicMock()
    mock_client.get_stock_bars.return_value = mock_bars

    df = load_recent(symbol, days=5, use_cache=True, client=mock_client, cache_dir=tmp_path)
    mock_client.get_stock_bars.assert_called_once()
    assert df is not None
    assert len(df) == 5
    assert list(df.columns) == ["open", "high", "low", "close", "volume"]
