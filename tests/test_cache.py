"""Tests for local market data caching."""

import pandas as pd
import pytest

from src.data.cache import (
    clear_cache,
    is_cached,
    load_from_cache,
    save_to_cache,
)


@pytest.fixture
def sample_df() -> pd.DataFrame:
    dates = pd.date_range("2026-01-01", periods=10, freq="B", name="date")
    return pd.DataFrame(
        {
            "open": [100.0 + i for i in range(10)],
            "high": [105.0 + i for i in range(10)],
            "low": [98.0 + i for i in range(10)],
            "close": [102.0 + i for i in range(10)],
            "volume": [1000000.0 + i * 1000 for i in range(10)],
        },
        index=dates,
    )


def test_cache_parquet_roundtrip(sample_df, tmp_path):
    symbol = "TESTPARQ"
    saved_path = save_to_cache(symbol, sample_df, format="parquet", custom_dir=tmp_path)
    assert saved_path.exists()
    assert is_cached(symbol, format="parquet", custom_dir=tmp_path)

    loaded_df = load_from_cache(symbol, format="parquet", custom_dir=tmp_path)
    assert loaded_df is not None
    assert isinstance(loaded_df.index, pd.DatetimeIndex)
    pd.testing.assert_frame_equal(sample_df, loaded_df, check_freq=False)


def test_cache_csv_roundtrip(sample_df, tmp_path):
    symbol = "TESTCSV"
    saved_path = save_to_cache(symbol, sample_df, format="csv", custom_dir=tmp_path)
    assert saved_path.exists()
    assert is_cached(symbol, format="csv", custom_dir=tmp_path)

    loaded_df = load_from_cache(symbol, format="csv", custom_dir=tmp_path)
    assert loaded_df is not None
    assert isinstance(loaded_df.index, pd.DatetimeIndex)
    pd.testing.assert_frame_equal(sample_df, loaded_df, check_freq=False)


def test_cache_not_found(tmp_path):
    assert not is_cached("NONEXISTENT", custom_dir=tmp_path)
    assert load_from_cache("NONEXISTENT", custom_dir=tmp_path) is None


def test_clear_cache(sample_df, tmp_path):
    save_to_cache("SYM1", sample_df, format="parquet", custom_dir=tmp_path)
    save_to_cache("SYM2", sample_df, format="csv", custom_dir=tmp_path)
    assert is_cached("SYM1", format="parquet", custom_dir=tmp_path)
    assert is_cached("SYM2", format="csv", custom_dir=tmp_path)

    # Clear single symbol
    removed = clear_cache("SYM1", custom_dir=tmp_path)
    assert removed == 1
    assert not is_cached("SYM1", format="parquet", custom_dir=tmp_path)
    assert is_cached("SYM2", format="csv", custom_dir=tmp_path)

    # Clear all
    removed_all = clear_cache(custom_dir=tmp_path)
    assert removed_all == 1
    assert not is_cached("SYM2", format="csv", custom_dir=tmp_path)
