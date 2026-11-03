"""Download the daily history (2006 - today) of the universe and SPY into data/cache/ once.

Run: PYTHONPATH=. uv run python scripts/download_history.py
Symbols already in the cache are skipped; failures are listed at the end.
"""

from __future__ import annotations

import sys

from src.data import BENCHMARK_SYMBOL, get_tradeable_symbols, load_daily

START = "2006-01-01"


def main() -> int:
    symbols = [BENCHMARK_SYMBOL, *get_tradeable_symbols()]
    failed = {}
    for i, sym in enumerate(symbols, 1):
        try:
            df = load_daily(sym, start=START)
            if df.empty:
                raise ValueError("no data (renamed or delisted symbol?)")
            first = df.index[0].date()
            print(f"[{i}/{len(symbols)}] {sym}: {len(df)} bars from {first}", flush=True)
        except Exception as exc:  # report every failure, keep going
            failed[sym] = f"{type(exc).__name__}: {exc}"
            print(f"[{i}/{len(symbols)}] {sym}: FAILED {failed[sym]}", flush=True)
    print(f"\nOK: {len(symbols) - len(failed)} / {len(symbols)}")
    for sym, err in failed.items():
        print(f"FAILED {sym}: {err}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
