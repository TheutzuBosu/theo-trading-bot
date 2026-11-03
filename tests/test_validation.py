"""Tests for data validation rules."""

import pandas as pd
import pytest

from src.data.validation import DataValidationError, validate


@pytest.fixture
def clean_df() -> pd.DataFrame:
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


def test_validate_clean_data(clean_df):
    # Should not raise any error
    validate(clean_df, symbol="TEST")


def test_validate_empty_data():
    with pytest.raises(DataValidationError, match="empty or None"):
        validate(pd.DataFrame(), symbol="TEST")


def test_validate_missing_columns(clean_df):
    bad_df = clean_df.drop(columns=["volume"])
    with pytest.raises(DataValidationError, match="Missing required columns.*volume"):
        validate(bad_df, symbol="TEST")


def test_validate_nan_values(clean_df):
    bad_df = clean_df.copy()
    bad_df.loc[bad_df.index[2], "close"] = float("nan")
    with pytest.raises(DataValidationError, match="NaN values found.*close"):
        validate(bad_df, symbol="TEST")


def test_validate_non_positive_price(clean_df):
    bad_df = clean_df.copy()
    bad_df.loc[bad_df.index[1], "low"] = 0.0
    with pytest.raises(DataValidationError, match="Non-positive price.*low"):
        validate(bad_df, symbol="TEST")

    bad_df.loc[bad_df.index[1], "low"] = -5.0
    with pytest.raises(DataValidationError, match="Non-positive price.*low"):
        validate(bad_df, symbol="TEST")


def test_validate_negative_volume(clean_df):
    bad_df = clean_df.copy()
    bad_df.loc[bad_df.index[0], "volume"] = -100.0
    with pytest.raises(DataValidationError, match="Negative volume found"):
        validate(bad_df, symbol="TEST")


def test_validate_duplicate_dates(clean_df):
    bad_dates = [
        clean_df.index[0],
        clean_df.index[0],
        clean_df.index[2],
        clean_df.index[3],
        clean_df.index[4],
    ]
    bad_df = clean_df.copy()
    bad_df.index = pd.DatetimeIndex(bad_dates)
    with pytest.raises(DataValidationError, match="duplicate date"):
        validate(bad_df, symbol="TEST")


def test_validate_non_monotonic_dates(clean_df):
    bad_dates = [
        clean_df.index[1],
        clean_df.index[0],
        clean_df.index[2],
        clean_df.index[3],
        clean_df.index[4],
    ]
    bad_df = clean_df.copy()
    bad_df.index = pd.DatetimeIndex(bad_dates)
    with pytest.raises(DataValidationError, match="not strictly monotonic increasing"):
        validate(bad_df, symbol="TEST")


def test_validate_high_low_inconsistency(clean_df):
    bad_df = clean_df.copy()
    # High < Low
    bad_df.loc[bad_df.index[0], "high"] = 95.0
    with pytest.raises(DataValidationError, match="High < Low"):
        validate(bad_df, symbol="TEST")

    bad_df = clean_df.copy()
    # High < Open
    bad_df.loc[bad_df.index[0], "open"] = 105.0
    with pytest.raises(DataValidationError, match="High < Open"):
        validate(bad_df, symbol="TEST")

    bad_df = clean_df.copy()
    # Low > Open
    bad_df.loc[bad_df.index[0], "low"] = 101.0
    bad_df.loc[bad_df.index[0], "open"] = 100.0
    bad_df.loc[bad_df.index[0], "close"] = 102.0
    with pytest.raises(DataValidationError, match="Low > Open"):
        validate(bad_df, symbol="TEST")

    bad_df = clean_df.copy()
    # Low > Close
    bad_df.loc[bad_df.index[0], "open"] = 104.0
    bad_df.loc[bad_df.index[0], "close"] = 102.0
    bad_df.loc[bad_df.index[0], "low"] = 103.0
    bad_df.loc[bad_df.index[0], "high"] = 105.0
    with pytest.raises(DataValidationError, match="Low > Close"):
        validate(bad_df, symbol="TEST")


def test_validate_ignores_float_rounding_in_adjusted_prices(clean_df):
    # yfinance adjusted bars: high and close equal up to the last float digit
    df = clean_df.copy()
    first = df.index[0]
    df.loc[first, ["open", "high", "low", "close"]] = [
        28.5,
        28.8222541809082,
        28.4,
        28.822254180908203,
    ]
    validate(df, symbol="TEST")

    df.loc[first, ["low", "close"]] = [42.57182693481446, 42.57182693481445]
    df.loc[first, ["open", "high"]] = [42.6, 42.9]
    validate(df, symbol="TEST")

    # a real gap of one cent is still an error
    df.loc[first, ["high", "close"]] = [42.9, 42.91]
    with pytest.raises(DataValidationError, match="High < Close"):
        validate(df, symbol="TEST")


def test_validate_abnormal_calendar_gap():
    # Gap of 14 days
    dates = [pd.Timestamp("2026-01-01"), pd.Timestamp("2026-01-15")]
    df = pd.DataFrame(
        {
            "open": [100.0, 102.0],
            "high": [103.0, 104.0],
            "low": [99.0, 101.0],
            "close": [102.0, 103.0],
            "volume": [1000.0, 1000.0],
        },
        index=pd.DatetimeIndex(dates),
    )
    with pytest.raises(DataValidationError, match="Abnormal calendar gap of 14 days"):
        validate(df, symbol="TEST", max_gap_days=7)


def test_validate_abnormal_price_jump(clean_df):
    bad_df = clean_df.copy()
    # 6x price jump from previous close
    bad_df.loc[bad_df.index[2], "close"] = bad_df.loc[bad_df.index[1], "close"] * 6.0
    bad_df.loc[bad_df.index[2], "high"] = bad_df.loc[bad_df.index[2], "close"] + 5.0
    with pytest.raises(DataValidationError, match="Abnormal price jump"):
        validate(bad_df, symbol="TEST", max_price_ratio_jump=5.0)
