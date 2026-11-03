"""Tests for the hard-coded FOMC calendar and the +/-30 minute entry veto."""

import pandas as pd
import pytest

from src.backtest.fomc import fomc_announcements, fomc_blocked
from src.data.intraday import nyse_sessions


def test_eight_in_session_announcements_per_year_on_nyse_sessions():
    ann = fomc_announcements()
    assert ann.year.value_counts().sort_index().tolist() == [8] * 11  # 2016..2026
    sessions = nyse_sessions("2016-01-01", "2026-12-31").index
    assert ann.tz_localize(None).normalize().isin(sessions).all()  # no weekend or holiday typos


def test_statement_times():
    ann = fomc_announcements()
    off_hour = ann[ann.strftime("%H:%M") != "14:00"]
    assert list(off_hour.strftime("%Y-%m-%d %H:%M")) == ["2020-03-03 10:00"]


def test_veto_window_boundaries():
    ts = pd.DatetimeIndex(
        ["2016-11-02 13:29", "2016-11-02 13:30", "2016-11-02 14:30", "2016-11-02 14:31",
         "2016-11-03 14:00"],
        tz="America/New_York",
    )  # fmt: skip
    assert fomc_blocked(ts).tolist() == [False, True, True, False, False]
    assert fomc_blocked(ts.tz_convert("UTC")).tolist() == [False, True, True, False, False]


def test_naive_timestamps_rejected():
    with pytest.raises(ValueError):
        fomc_blocked(pd.DatetimeIndex(["2016-11-02 14:00"]))
