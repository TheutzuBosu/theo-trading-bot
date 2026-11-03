"""Tests for minute-bar validation and the SIP vs IEX comparison (offline, small real fixture)."""

from pathlib import Path

import pandas as pd
import pytest

from src.data.feed_compare import compare_feeds, session_vwap
from src.data.intraday import nyse_sessions
from src.data.intraday_validation import expected_bars, is_clean, validate_minute_bars

FIXTURE = Path(__file__).parent / "fixtures" / "minute_spy_sip_2016-11.csv"


@pytest.fixture
def bars() -> pd.DataFrame:
    # SPY SIP, 23 Nov 2016 (full day) and 25 Nov 2016 (13:00 early close); 24 Nov is a holiday
    df = pd.read_csv(FIXTURE, index_col=0)
    df.index = pd.to_datetime(df.index, utc=True).tz_convert("America/New_York")
    return df


def test_expected_bars():
    exp = expected_bars(nyse_sessions("2016-11-23", "2016-11-25"))
    assert list(exp) == [390, 210]


def test_fixture_is_clean(bars):
    rep = validate_minute_bars(bars)
    assert rep["sessions"] == 2
    assert rep["bars"] == 600
    assert rep["early_closes"] == ["2016-11-25"]
    assert is_clean(rep), rep


def test_detects_missing_day(bars):
    rep = validate_minute_bars(bars, start="2016-11-22", end="2016-11-25")
    assert rep["missing_days"] == ["2016-11-22"]
    assert not is_clean(rep)


def test_detects_short_session_and_duplicates(bars):
    # Drop 30 minutes on 23 Nov, duplicate one bar on 25 Nov
    df = bars.drop(bars.index[100:130])
    df = pd.concat([df, df.iloc[[-1]]]).sort_index()
    rep = validate_minute_bars(df)
    assert rep["short_sessions"] == {"2016-11-23": [360, 390]}
    assert rep["duplicates"] == 1
    assert not is_clean(rep)


def test_detects_outside_session_and_bad_ohlc(bars):
    df = bars.copy()
    late = df.iloc[[-1]].copy()
    late.index = late.index + pd.Timedelta(minutes=30)  # 13:29 on an early-close day
    df.iloc[5, df.columns.get_loc("high")] = df.iloc[5]["low"] - 1.0
    df = pd.concat([df, late]).sort_index()
    rep = validate_minute_bars(df)
    assert rep["outside_session"] == 1
    assert rep["bad_ohlc"] == 1


def test_detects_extra_day(bars):
    holiday = bars.iloc[:5].copy()
    holiday.index = holiday.index + pd.Timedelta(days=1)  # Thanksgiving
    rep = validate_minute_bars(pd.concat([bars, holiday]).sort_index())
    assert rep["extra_days"] == ["2016-11-24"]


def test_session_vwap_resets_each_day(bars):
    v = session_vwap(bars)
    first = bars.index[0]
    assert v[first] == pytest.approx(bars.loc[first, "vwap"])
    day2 = bars.index[390]
    assert v[day2] == pytest.approx(bars.loc[day2, "vwap"])
    assert v.notna().all()


def test_compare_feeds_identical(bars):
    rep = compare_feeds(bars, bars)
    assert rep["days"] == 2
    assert rep["coverage"] == 1.0
    assert rep["volume_share"] == 1.0
    assert rep["close_bps"]["max"] == 0.0
    assert rep["vwap_bps"]["max"] == pytest.approx(0.0)


def test_compare_feeds_shifted_and_sparse(bars):
    iex = bars.iloc[::2].copy()  # half of the minutes
    iex[["open", "high", "low", "close", "vwap"]] *= 1.0001  # +1 bp
    iex["volume"] *= 0.03
    rep = compare_feeds(bars, iex)
    assert rep["coverage"] == pytest.approx(0.5)
    assert rep["volume_share"] == pytest.approx(0.03)
    assert rep["close_bps"]["median"] == pytest.approx(1.0, abs=1e-3)
    assert rep["close_bps"]["bias"] == pytest.approx(1.0, abs=1e-3)
    assert rep["vwap_bps"]["n"] == 600
    assert rep["vwap_bps_after_30min"]["n"] == 600 - 60


def test_compare_feeds_no_overlap(bars):
    other = bars.copy()
    other.index = other.index + pd.Timedelta(days=7)
    with pytest.raises(ValueError):
        compare_feeds(bars, other)
