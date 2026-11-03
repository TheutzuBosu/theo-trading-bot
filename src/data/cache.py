"""Local caching for market data using parquet and csv."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Literal

import pandas as pd

from src.config import settings

logger = logging.getLogger(__name__)

CacheFormat = Literal["parquet", "csv"]


def get_cache_dir(custom_dir: Path | str | None = None) -> Path:
    """Return the cache directory, creating it if necessary."""
    path = Path(custom_dir) if custom_dir is not None else settings.CACHE_DIR
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_cache_path(
    symbol: str,
    format: CacheFormat = "parquet",
    custom_dir: Path | str | None = None,
) -> Path:
    """Return the filesystem path for a cached symbol."""
    cache_dir = get_cache_dir(custom_dir)
    sanitized = symbol.strip().upper().replace("/", "_").replace(".", "_")
    extension = "parquet" if format == "parquet" else "csv"
    return cache_dir / f"{sanitized}.{extension}"


def save_to_cache(
    symbol: str,
    df: pd.DataFrame,
    format: CacheFormat = "parquet",
    custom_dir: Path | str | None = None,
) -> Path:
    """Save a DataFrame of market data to cache.

    Args:
        symbol: Ticker symbol (e.g. 'AAPL').
        df: DataFrame with DatetimeIndex.
        format: 'parquet' or 'csv'.
        custom_dir: Optional custom cache directory.

    Returns:
        Path to the saved cache file.
    """
    file_path = get_cache_path(symbol, format=format, custom_dir=custom_dir)
    try:
        if format == "parquet":
            df.to_parquet(file_path)
        else:
            df.to_csv(file_path, index=True)
        logger.debug("Saved %s cache to %s (%d rows)", symbol, file_path, len(df))
    except Exception as e:
        logger.warning("Failed to save %s cache to %s: %s", symbol, file_path, e)
        raise
    return file_path


def load_from_cache(
    symbol: str,
    format: CacheFormat = "parquet",
    custom_dir: Path | str | None = None,
) -> pd.DataFrame | None:
    """Load a DataFrame of market data from cache if present.

    Returns:
        DataFrame with DatetimeIndex, or None if not cached.
    """
    file_path = get_cache_path(symbol, format=format, custom_dir=custom_dir)
    if not file_path.exists():
        return None

    try:
        if format == "parquet":
            df = pd.read_parquet(file_path)
        else:
            df = pd.read_csv(file_path, index_col=0, parse_dates=True)

        if not isinstance(df.index, pd.DatetimeIndex):
            df.index = pd.to_datetime(df.index)

        # Standardize index name
        df.index.name = "date"
        logger.debug("Loaded %s from cache %s (%d rows)", symbol, file_path, len(df))
        return df
    except Exception as e:
        logger.warning("Failed to read cache file %s for %s: %s", file_path, symbol, e)
        return None


def is_cached(
    symbol: str,
    format: CacheFormat = "parquet",
    custom_dir: Path | str | None = None,
) -> bool:
    """Check if cache file exists for symbol."""
    return get_cache_path(symbol, format=format, custom_dir=custom_dir).exists()


def clear_cache(
    symbol: str | None = None,
    custom_dir: Path | str | None = None,
) -> int:
    """Clear cached files.

    If symbol is provided, deletes only that symbol's cache.
    Otherwise deletes all cache files in the directory.

    Returns:
        Number of files removed.
    """
    cache_dir = get_cache_dir(custom_dir)
    count = 0
    if symbol:
        for fmt in ("parquet", "csv"):
            p = get_cache_path(symbol, format=fmt, custom_dir=cache_dir)
            if p.exists():
                p.unlink()
                count += 1
    else:
        for f in cache_dir.glob("*"):
            if f.is_file() and f.suffix in (".parquet", ".csv"):
                f.unlink()
                count += 1
    return count
