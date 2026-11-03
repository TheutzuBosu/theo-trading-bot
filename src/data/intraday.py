"""1-minute bars for Faza B (SPY/QQQ): NYSE calendar, session filter, Alpaca fetch, cache paths."""

from __future__ import annotations

import datetime as dt
from functools import lru_cache
from pathlib import Path

import exchange_calendars as xc
import pandas as pd

from src.config import settings
from src.data.market_time import NY_TZ

MINUTE_COLUMNS = ["open", "high", "low", "close", "volume", "trade_count", "vwap"]
# Free plan: SIP data is not allowed in the last 15 minutes (D23)
SIP_DELAY = dt.timedelta(minutes=16)


@lru_cache(maxsize=1)
def _xnys():
    return xc.get_calendar("XNYS")


def nyse_sessions(start: str | dt.date, end: str | dt.date) -> pd.DataFrame:
    """NYSE regular sessions between start and end (inclusive).

    Returns a DataFrame indexed by session date (naive) with `open` and `close` in New York time.
    Early closes (13:00 ET) and holidays come from the exchange calendar, offline.
    """
    sched = _xnys().schedule.loc[pd.Timestamp(start) : pd.Timestamp(end), ["open", "close"]]
    out = pd.DataFrame(
        {
            "open": sched["open"].dt.tz_convert(NY_TZ),
            "close": sched["close"].dt.tz_convert(NY_TZ),
        },
        index=pd.DatetimeIndex(sched.index.date, name="session"),
    )
    return out


def last_closed_session(now: dt.datetime | None = None, delay: dt.timedelta = SIP_DELAY) -> dt.date:
    """Most recent session closed at least `delay` ago (a complete day of SIP data)."""
    now = now or dt.datetime.now(dt.UTC)
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    sessions = nyse_sessions(now.date() - dt.timedelta(days=10), now.date())
    closed = sessions[sessions["close"] <= pd.Timestamp(now - delay)]
    return closed.index[-1].date()


def to_ny_index(df: pd.DataFrame) -> pd.DataFrame:
    """Convert a tz-aware DatetimeIndex to New York time, named `timestamp`."""
    out = df.copy()
    if out.index.tz is None:
        raise ValueError("minute bars must have a timezone-aware index")
    out.index = out.index.tz_convert(NY_TZ)
    out.index.name = "timestamp"
    return out


def filter_regular_session(df: pd.DataFrame, sessions: pd.DataFrame) -> pd.DataFrame:
    """Keep only bars that start inside a regular session: open <= t < close (NY time).

    Bars are labelled by their start minute, so a full day is 9:30..15:59 = 390 bars
    (210 on a 13:00 early close). Bars on non-session days are dropped.
    """
    if df.empty:
        return df
    bars = to_ny_index(df)
    day = pd.DatetimeIndex(bars.index.date)
    # Non-session days map to NaT, and comparisons with NaT are False
    opens = pd.DatetimeIndex(sessions["open"].reindex(day))
    closes = pd.DatetimeIndex(sessions["close"].reindex(day))
    mask = (bars.index >= opens) & (bars.index < closes)
    return bars.loc[mask]


def fetch_minute_bars(
    client,
    symbol: str,
    start: dt.datetime,
    end: dt.datetime,
    feed: str = "sip",
) -> pd.DataFrame:
    """Download raw (unadjusted) 1-minute bars from Alpaca for one symbol.

    `client` is an `alpaca.data.historical.StockHistoricalDataClient`; the SDK paginates.
    Returns columns MINUTE_COLUMNS with a New York tz index (extended hours included).
    """
    from alpaca.data.enums import Adjustment, DataFeed
    from alpaca.data.requests import StockBarsRequest
    from alpaca.data.timeframe import TimeFrame

    req = StockBarsRequest(
        symbol_or_symbols=symbol,
        timeframe=TimeFrame.Minute,
        start=start,
        end=end,
        feed=DataFeed(feed),
        adjustment=Adjustment.RAW,
    )
    raw = client.get_stock_bars(req).df
    if raw is None or raw.empty:
        return pd.DataFrame(columns=MINUTE_COLUMNS, index=pd.DatetimeIndex([], tz=NY_TZ))
    if isinstance(raw.index, pd.MultiIndex):
        raw = raw.xs(symbol, level="symbol")
    return to_ny_index(raw[MINUTE_COLUMNS])


def minute_cache_path(
    symbol: str, feed: str, year: int, cache_dir: Path | str | None = None
) -> Path:
    """Cache file for one symbol/feed/year: data/cache/minute/<FEED>/<SYMBOL>/<year>.parquet."""
    base = Path(cache_dir) if cache_dir is not None else settings.CACHE_DIR / "minute"
    return base / feed.upper() / symbol.upper() / f"{year}.parquet"


def load_minute_bars(
    symbol: str,
    feed: str = "sip",
    start: str | None = None,
    end: str | None = None,
    cache_dir: Path | str | None = None,
) -> pd.DataFrame:
    """Load cached session bars for a symbol/feed, concatenated over years, optionally sliced."""
    folder = minute_cache_path(symbol, feed, 2000, cache_dir).parent
    files = sorted(folder.glob("*.parquet"))
    if not files:
        raise FileNotFoundError(
            f"no cached minute bars in {folder}; run scripts/download_minute.py"
        )
    df = pd.concat([pd.read_parquet(f) for f in files]).sort_index()
    if start is not None:
        df = df[df.index >= pd.Timestamp(start, tz=NY_TZ)]
    if end is not None:
        df = df[df.index < pd.Timestamp(end, tz=NY_TZ) + pd.Timedelta(days=1)]
    return df
