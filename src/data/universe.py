"""Stock universe loader and helper functions."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from src.config import settings

BENCHMARK_SYMBOL = "SPY"


def load_universe(path: Path | str | None = None) -> pd.DataFrame:
    """Load the stock universe from universe.csv.

    Args:
        path: Path to universe.csv. Defaults to config/universe.csv from settings.

    Returns:
        DataFrame containing 'symbol' and 'sector' columns.
    """
    csv_path = Path(path) if path is not None else settings.UNIVERSE_PATH
    if not csv_path.exists():
        raise FileNotFoundError(f"Universe file not found at {csv_path}")

    df = pd.read_csv(csv_path)
    df["symbol"] = df["symbol"].astype(str).str.strip().str.upper()
    df["sector"] = df["sector"].astype(str).str.strip()
    return df


def get_tradeable_symbols(path: Path | str | None = None) -> list[str]:
    """Return all tradeable symbols from the universe (excludes benchmark SPY)."""
    df = load_universe(path)
    return df[df["symbol"] != BENCHMARK_SYMBOL]["symbol"].tolist()


def get_benchmark_symbol() -> str:
    """Return the benchmark symbol."""
    return BENCHMARK_SYMBOL


def get_symbol_sector(symbol: str, path: Path | str | None = None) -> str | None:
    """Return the sector for a given symbol, or None if not found."""
    df = load_universe(path)
    matches = df[df["symbol"] == symbol.upper()]
    if matches.empty:
        return None
    return str(matches["sector"].iloc[0])
