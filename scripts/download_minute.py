"""Faza B, B1: download 1-minute bars for SPY and QQQ from Alpaca (one-time run).

- SIP (consolidated) from 2016-01-04 (D23) and IEX from 2020-07-27 (for the SIP vs IEX check).
- Only the regular session (9:30-16:00 ET, 13:00 on early closes), raw prices (no adjustment).
- Ends at the last fully closed session (the free plan forbids SIP in the last 15 minutes).
- One parquet per symbol/feed/year in data/cache/minute/ (not in git). Finished years are skipped,
  so a rerun only refreshes the current year.

Read-only: places no orders. Summary in .cache/download_minute.json.
Run: PYTHONPATH=. uv run python scripts/download_minute.py
"""

import datetime as dt
import json
import time
from pathlib import Path

import pandas as pd
from alpaca.data.historical import StockHistoricalDataClient

from src.config import settings
from src.data.intraday import (
    fetch_minute_bars,
    filter_regular_session,
    last_closed_session,
    minute_cache_path,
    nyse_sessions,
)

SYMBOLS = ["SPY", "QQQ"]
FEED_START = {"sip": dt.date(2016, 1, 4), "iex": dt.date(2020, 7, 27)}
OUT = Path(__file__).resolve().parent.parent / ".cache" / "download_minute.json"


def download_year(client, symbol: str, feed: str, start: dt.date, end: dt.date) -> pd.DataFrame:
    """Session bars between start and end (inclusive), fetched month by month."""
    sessions = nyse_sessions(start, end)
    parts = []
    for month_start in pd.date_range(pd.Timestamp(start).replace(day=1), end, freq="MS"):
        m_start = max(month_start.date(), start)
        m_end = min((month_start + pd.offsets.MonthEnd(0)).date(), end)
        t0 = dt.datetime.combine(m_start, dt.time(0, 0), tzinfo=dt.UTC)
        t1 = dt.datetime.combine(m_end + dt.timedelta(days=1), dt.time(4, 0), tzinfo=dt.UTC)
        for attempt in range(3):
            try:
                raw = fetch_minute_bars(client, symbol, t0, t1, feed=feed)
                break
            except Exception as exc:  # noqa: BLE001
                if attempt == 2:
                    raise
                print(f"  retry {symbol} {feed} {m_start}: {str(exc)[:120]}")
                time.sleep(10)
        parts.append(filter_regular_session(raw, sessions))
    df = pd.concat(parts).sort_index()
    return df[~df.index.duplicated(keep="first")]


def main() -> None:
    client = StockHistoricalDataClient(settings.ALPACA_API_KEY, settings.ALPACA_SECRET_KEY)
    end = last_closed_session()
    summary = {"end": end.isoformat(), "files": {}}
    for feed, first_day in FEED_START.items():
        for symbol in SYMBOLS:
            for year in range(first_day.year, end.year + 1):
                path = minute_cache_path(symbol, feed, year)
                y_start = max(first_day, dt.date(year, 1, 1))
                y_end = min(end, dt.date(year, 12, 31))
                if path.exists() and year < end.year:
                    summary["files"][str(path)] = "skipped (exists)"
                    continue
                t = time.time()
                df = download_year(client, symbol, feed, y_start, y_end)
                path.parent.mkdir(parents=True, exist_ok=True)
                df.to_parquet(path)
                days = len(set(df.index.date))
                msg = f"{len(df)} bars, {days} days, {time.time() - t:.0f}s"
                summary["files"][str(path)] = msg
                print(f"{feed} {symbol} {year}: {msg}", flush=True)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(summary, indent=2))
    print(f"done, end={end}, summary in {OUT}")


if __name__ == "__main__":
    main()
