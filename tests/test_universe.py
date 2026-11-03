"""Tests for universe loading and configuration."""

from src.data.universe import (
    BENCHMARK_SYMBOL,
    get_benchmark_symbol,
    get_symbol_sector,
    get_tradeable_symbols,
    load_universe,
)


def test_load_universe():
    df = load_universe()
    assert not df.empty
    assert "symbol" in df.columns
    assert "sector" in df.columns
    # S&P 100 constituents + SPY >= 101 symbols
    assert len(df) >= 101
    assert BENCHMARK_SYMBOL in df["symbol"].values


def test_get_tradeable_symbols_excludes_benchmark():
    symbols = get_tradeable_symbols()
    assert BENCHMARK_SYMBOL not in symbols
    assert "AAPL" in symbols
    assert "MSFT" in symbols
    assert "NVDA" in symbols


def test_get_benchmark_symbol():
    assert get_benchmark_symbol() == "SPY"


def test_get_symbol_sector():
    assert get_symbol_sector("AAPL") == "Information Technology"
    assert get_symbol_sector("XOM") == "Energy"
    assert get_symbol_sector("JPM") == "Financials"
    assert get_symbol_sector("NONEXISTENT_TICKER") is None
