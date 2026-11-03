"""Market data loader using yfinance (historical) and Alpaca Market Data (recent)."""

from __future__ import annotations

import datetime as dt
import logging
from pathlib import Path
from typing import Sequence
from zoneinfo import ZoneInfo

import pandas as pd
import yfinance as yf
from alpaca.data.enums import DataFeed
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame

from src.config import settings
from src.data.cache import CacheFormat, load_from_cache, save_to_cache
from src.data.market_time import drop_incomplete_bar
from src.data.validation import validate

logger = logging.getLogger(__name__)

NY_TZ = ZoneInfo("America/New_York")
DEFAULT_HISTORY_YEARS = 20
REQUIRED_COLUMNS = ["open", "high", "low", "close", "volume"]


def _standardize_dataframe(df: pd.DataFrame, symbol: str | None = None) -> pd.DataFrame:
    """Standardize column names to lowercase and keep only standard OHLCV columns."""
    if df is None or df.empty:
        return pd.DataFrame(columns=REQUIRED_COLUMNS)

    clean_df = df.copy()

    # Flatten MultiIndex columns if present
    if isinstance(clean_df.columns, pd.MultiIndex):
        if symbol and symbol in clean_df.columns.levels[1]:
            clean_df = clean_df.xs(symbol, axis=1, level=1)
        elif symbol and symbol in clean_df.columns.levels[0]:
            clean_df = clean_df.xs(symbol, axis=1, level=0)
        else:
            clean_df.columns = [
                "_".join(str(c) for c in col if c).strip() for col in clean_df.columns
            ]

    # Map column names to lowercase
    rename_map = {}
    for col in clean_df.columns:
        col_lower = str(col).lower()
        if col_lower in REQUIRED_COLUMNS:
            rename_map[col] = col_lower
        elif col_lower in ["adj close", "adj_close"]:
            rename_map[col] = "close"

    clean_df = clean_df.rename(columns=rename_map)

    # Keep only standard columns if present
    present_cols = [c for c in REQUIRED_COLUMNS if c in clean_df.columns]
    clean_df = clean_df[present_cols].copy()

    # Ensure index is DatetimeIndex normalized to midnight date
    if not isinstance(clean_df.index, pd.DatetimeIndex):
        clean_df.index = pd.to_datetime(clean_df.index)

    # Convert timezone if tz-aware, then strip to date
    if clean_df.index.tz is not None:
        clean_df.index = clean_df.index.tz_convert(NY_TZ)
    clean_df.index = pd.to_datetime(clean_df.index.date)
    clean_df.index.name = "date"

    # Sort index
    clean_df = clean_df.sort_index()

    # Remove any duplicate dates keeping the last
    if clean_df.index.duplicated().any():
        clean_df = clean_df[~clean_df.index.duplicated(keep="last")]

    # Cast types
    for col in ["open", "high", "low", "close"]:
        if col in clean_df.columns:
            clean_df[col] = clean_df[col].astype(float)
    if "volume" in clean_df.columns:
        clean_df["volume"] = clean_df["volume"].astype(float)

    return clean_df


def yahoo_symbol(symbol: str) -> str:
    """Symbol as yfinance knows it: class shares use '-' (BRK.B -> BRK-B), Alpaca uses '.'."""
    return symbol.replace(".", "-")


def _get_default_start_date(years: int = DEFAULT_HISTORY_YEARS) -> str:
    """Return default start date string N years ago."""
    now = dt.datetime.now(NY_TZ)
    start_year = now.year - years
    return f"{start_year}-01-01"


def load_daily(
    symbols: str | Sequence[str],
    start: str | dt.date | dt.datetime | None = None,
    end: str | dt.date | dt.datetime | None = None,
    use_cache: bool = True,
    cache_format: CacheFormat = "parquet",
    validate_data: bool = True,
    cache_dir: Path | str | None = None,
) -> pd.DataFrame | dict[str, pd.DataFrame]:
    """Load daily market data with yfinance (auto_adjust=True) for ~20 years history.

    Args:
        symbols: Single symbol (e.g. 'AAPL') or sequence of symbols.
        start: Start date string or date. Defaults to ~20 years ago.
        end: End date string or date. Defaults to current date.
        use_cache: If True, uses local cache in data/cache/.
        cache_format: 'parquet' (preferred) or 'csv'.
        validate_data: If True, validates data integrity.
        cache_dir: Optional custom cache directory.

    Returns:
        DataFrame for single symbol, or dict of {symbol: DataFrame} for multiple.
    """
    single_symbol = isinstance(symbols, str)
    sym_list = [symbols.upper()] if single_symbol else [s.upper() for s in symbols]

    start_str = (
        start.strftime("%Y-%m-%d")
        if isinstance(start, (dt.date, dt.datetime))
        else (start or _get_default_start_date())
    )
    end_str = end.strftime("%Y-%m-%d") if isinstance(end, (dt.date, dt.datetime)) else end

    results: dict[str, pd.DataFrame] = {}

    for sym in sym_list:
        df: pd.DataFrame | None = None

        if use_cache:
            df = load_from_cache(sym, format=cache_format, custom_dir=cache_dir)
            if df is not None and not df.empty:
                # Filter requested date range
                if start_str:
                    df = df[df.index >= pd.to_datetime(start_str)]
                if end_str:
                    df = df[df.index <= pd.to_datetime(end_str)]

        if df is None or df.empty:
            ticker = yf.Ticker(yahoo_symbol(sym))
            raw = ticker.history(
                start=start_str,
                end=end_str,
                auto_adjust=True,
                actions=False,
            )
            df = _standardize_dataframe(raw, symbol=sym)
            df = drop_incomplete_bar(df)

            if validate_data and not df.empty:
                validate(df, symbol=sym)

            if use_cache and not df.empty:
                save_to_cache(sym, df, format=cache_format, custom_dir=cache_dir)

        results[sym] = df

    return results[sym_list[0]] if single_symbol else results


def load_recent(
    symbols: str | Sequence[str],
    days: int = 30,
    use_cache: bool = True,
    cache_format: CacheFormat = "parquet",
    client: StockHistoricalDataClient | None = None,
    validate_data: bool = True,
    cache_dir: Path | str | None = None,
) -> pd.DataFrame | dict[str, pd.DataFrame]:
    """Load recent daily bars using Alpaca Market Data (feed IEX, free tier).

    Args:
        symbols: Single symbol or sequence of symbols.
        days: Number of calendar days to fetch (defaults to 30).
        use_cache: If True, merges recent bars into local cache.
        cache_format: 'parquet' or 'csv'.
        client: Optional pre-configured StockHistoricalDataClient.
        validate_data: If True, validates data.
        cache_dir: Optional custom cache directory.

    Returns:
        DataFrame for single symbol, or dict of {symbol: DataFrame} for multiple.
    """
    single_symbol = isinstance(symbols, str)
    sym_list = [symbols.upper()] if single_symbol else [s.upper() for s in symbols]

    if client is None:
        client = StockHistoricalDataClient(
            api_key=settings.ALPACA_API_KEY or None,
            secret_key=settings.ALPACA_SECRET_KEY or None,
        )

    # Ensure buffer for calendar days to guarantee enough trading days
    lookback_days = max(days * 2, 30)
    start_dt = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=lookback_days)

    request = StockBarsRequest(
        symbol_or_symbols=sym_list,
        timeframe=TimeFrame.Day,
        start=start_dt,
        feed=DataFeed.IEX,
    )

    bars = client.get_stock_bars(request)
    raw_df = bars.df

    results: dict[str, pd.DataFrame] = {}

    for sym in sym_list:
        if raw_df is None or raw_df.empty:
            df = pd.DataFrame(columns=REQUIRED_COLUMNS)
        else:
            if isinstance(raw_df.index, pd.MultiIndex):
                if sym in raw_df.index.levels[0]:
                    sym_raw = raw_df.xs(sym, level=0)
                else:
                    sym_raw = pd.DataFrame(columns=REQUIRED_COLUMNS)
            else:
                sym_raw = raw_df

            df = _standardize_dataframe(sym_raw, symbol=sym)

        # Slice to requested days
        if not df.empty and days > 0:
            df = df.iloc[-days:]

        df = drop_incomplete_bar(df)

        if validate_data and not df.empty:
            validate(df, symbol=sym)

        if use_cache and not df.empty:
            # Merge with existing cache if present
            existing = load_from_cache(sym, format=cache_format, custom_dir=cache_dir)
            if existing is not None and not existing.empty:
                combined = pd.concat([existing, df])
                combined = combined[~combined.index.duplicated(keep="last")].sort_index()
                save_to_cache(sym, combined, format=cache_format, custom_dir=cache_dir)
                df = combined
            else:
                save_to_cache(sym, df, format=cache_format, custom_dir=cache_dir)

        results[sym] = df

    return results[sym_list[0]] if single_symbol else results
