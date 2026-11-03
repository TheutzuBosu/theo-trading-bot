"""Tests for src/data/intraday.py (offline)."""

import datetime as dt

import pandas as pd
import pytest

from src.data.intraday import (
    MINUTE_COLUMNS,
    fetch_minute_bars,
    filter_regular_session,
    last_closed_session,
    load_minute_bars,
    minute_cache_path,
    nyse_sessions,
)
from src.data.market_time import NY_TZ


def _bars(start_ny: str, periods: int) -> pd.DataFrame:
    idx = pd.date_range(pd.Timestamp(start_ny, tz=NY_TZ), periods=periods, freq="1min").tz_convert(
        "UTC"
    )
    df = pd.DataFrame(1.0, index=idx, columns=MINUTE_COLUMNS)
    df["volume"] = 100.0
    return df


def test_nyse_sessions_holidays_and_early_close():
    s = nyse_sessions("2016-11-23", "2016-11-28")
    # Thanksgiving (24 Nov) is closed; 25 Nov closes at 13:00 ET
    assert [d.day for d in s.index] == [23, 25, 28]
    assert s.loc["2016-11-25", "close"].hour == 13
    assert s.loc["2016-11-23", "open"].strftime("%H:%M") == "09:30"
    assert s.loc["2016-11-23", "close"].hour == 16


def test_filter_regular_session_full_day():
    # 4:00 -> 20:00 ET, extended hours included
    df = _bars("2016-03-01 04:00", 16 * 60)
    out = filter_regular_session(df, nyse_sessions("2016-03-01", "2016-03-01"))
    assert len(out) == 390
    assert out.index[0].strftime("%H:%M") == "09:30"
    assert out.index[-1].strftime("%H:%M") == "15:59"
    assert str(out.index.tz) == "America/New_York"


def test_filter_regular_session_early_close_and_dst():
    early = _bars("2016-11-25 09:00", 8 * 60)
    out = filter_regular_session(early, nyse_sessions("2016-11-25", "2016-11-25"))
    assert len(out) == 210
    # Summer time: 9:30 ET is 13:30 UTC
    summer = _bars("2020-07-01 09:00", 8 * 60)
    out = filter_regular_session(summer, nyse_sessions("2020-07-01", "2020-07-01"))
    assert out.index[0].tz_convert("UTC").hour == 13
    assert len(out) == 390


def test_filter_regular_session_drops_non_session_days():
    weekend = _bars("2016-03-05 09:30", 390)  # Saturday
    out = filter_regular_session(weekend, nyse_sessions("2016-03-01", "2016-03-10"))
    assert out.empty


def test_last_closed_session():
    # Tuesday 3 Nov 2026, 14:31 ET: today's session is not closed yet
    now = dt.datetime(2026, 11, 3, 19, 31, tzinfo=dt.UTC)
    assert last_closed_session(now) == dt.date(2026, 11, 2)
    # 16:10 ET: closed, but SIP still inside the 15-minute delay
    assert last_closed_session(dt.datetime(2026, 11, 3, 21, 10, tzinfo=dt.UTC)) == dt.date(
        2026, 11, 2
    )
    assert last_closed_session(dt.datetime(2026, 11, 3, 21, 20, tzinfo=dt.UTC)) == dt.date(
        2026, 11, 3
    )
    with pytest.raises(ValueError):
        last_closed_session(dt.datetime(2026, 11, 3, 12, 0))


class _FakeBarSet:
    def __init__(self, df):
        self.df = df


class _FakeClient:
    def __init__(self, df):
        self._df = df
        self.requests = []

    def get_stock_bars(self, req):
        self.requests.append(req)
        return _FakeBarSet(self._df)


def test_fetch_minute_bars_multiindex():
    raw = _bars("2016-03-01 09:30", 3)
    raw.index.name = "timestamp"
    raw = pd.concat({"SPY": raw}, names=["symbol"])
    client = _FakeClient(raw)
    start = dt.datetime(2016, 3, 1, tzinfo=dt.UTC)
    out = fetch_minute_bars(client, "SPY", start, start + dt.timedelta(days=1), feed="sip")
    assert list(out.columns) == MINUTE_COLUMNS
    assert len(out) == 3
    assert str(out.index.tz) == "America/New_York"
    req = client.requests[0]
    assert req.feed.value == "sip"
    assert req.adjustment.value == "raw"


def test_fetch_minute_bars_empty():
    client = _FakeClient(pd.DataFrame())
    start = dt.datetime(2016, 3, 1, tzinfo=dt.UTC)
    out = fetch_minute_bars(client, "SPY", start, start + dt.timedelta(days=1))
    assert out.empty


def test_cache_path_and_load(tmp_path):
    p = minute_cache_path("spy", "sip", 2016, tmp_path)
    assert p == tmp_path / "SIP" / "SPY" / "2016.parquet"
    p.parent.mkdir(parents=True)
    filter_regular_session(
        _bars("2016-03-01 09:30", 390), nyse_sessions("2016-03-01", "2016-03-01")
    ).to_parquet(p)
    p2 = minute_cache_path("SPY", "sip", 2017, tmp_path)
    filter_regular_session(
        _bars("2017-03-01 09:30", 390), nyse_sessions("2017-03-01", "2017-03-01")
    ).to_parquet(p2)
    assert len(load_minute_bars("SPY", "sip", cache_dir=tmp_path)) == 780
    assert len(load_minute_bars("SPY", "sip", start="2017-01-01", cache_dir=tmp_path)) == 390
    assert len(load_minute_bars("SPY", "sip", end="2016-03-01", cache_dir=tmp_path)) == 390
    with pytest.raises(FileNotFoundError):
        load_minute_bars("QQQ", "sip", cache_dir=tmp_path)
