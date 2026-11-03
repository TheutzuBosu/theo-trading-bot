"""FOMC announcement times 2016-2026 for the deterministic no-entry veto (Faza B, D27).

Scheduled statements are released at 14:00 New York time (the second day of each meeting).
2021-2026 checked against federalreserve.gov/monetarypolicy/fomccalendars.htm on 3.11.2026;
2016-2020 from the Fed's historical calendars. Unscheduled announcements inside the cash session
are listed with their own time (2020-03-03, 10:00). Announcements outside the session (Sunday
2020-03-15) cannot block an entry and are left out. Notation votes are not announcements.
"""

from __future__ import annotations

import datetime as dt

import numpy as np
import pandas as pd

from src.data.market_time import NY_TZ

STATEMENT_TIME = dt.time(14, 0)
VETO_WINDOW = pd.Timedelta(minutes=30)

SCHEDULED = {
    2016: ("01-27", "03-16", "04-27", "06-15", "07-27", "09-21", "11-02", "12-14"),
    2017: ("02-01", "03-15", "05-03", "06-14", "07-26", "09-20", "11-01", "12-13"),
    2018: ("01-31", "03-21", "05-02", "06-13", "08-01", "09-26", "11-08", "12-19"),
    2019: ("01-30", "03-20", "05-01", "06-19", "07-31", "09-18", "10-30", "12-11"),
    2020: ("01-29", "04-29", "06-10", "07-29", "09-16", "11-05", "12-16"),
    2021: ("01-27", "03-17", "04-28", "06-16", "07-28", "09-22", "11-03", "12-15"),
    2022: ("01-26", "03-16", "05-04", "06-15", "07-27", "09-21", "11-02", "12-14"),
    2023: ("02-01", "03-22", "05-03", "06-14", "07-26", "09-20", "11-01", "12-13"),
    2024: ("01-31", "03-20", "05-01", "06-12", "07-31", "09-18", "11-07", "12-18"),
    2025: ("01-29", "03-19", "05-07", "06-18", "07-30", "09-17", "10-29", "12-10"),
    2026: ("01-28", "03-18", "04-29", "06-17", "07-29", "09-16", "10-28", "12-09"),
}
# The scheduled 2020-03-18 statement was replaced by the Sunday 2020-03-15 cut (outside the session)
UNSCHEDULED = ("2020-03-03 10:00",)


def fomc_announcements() -> pd.DatetimeIndex:
    """All in-session FOMC announcement times, New York time, sorted."""
    times = [
        pd.Timestamp(dt.datetime.combine(dt.date.fromisoformat(f"{y}-{md}"), STATEMENT_TIME))
        for y, days in SCHEDULED.items()
        for md in days
    ]
    times += [pd.Timestamp(t) for t in UNSCHEDULED]
    return pd.DatetimeIndex(sorted(times)).tz_localize(NY_TZ)


def fomc_blocked(timestamps: pd.DatetimeIndex, window: pd.Timedelta = VETO_WINDOW) -> np.ndarray:
    """True for bars starting within `window` before or after an FOMC announcement."""
    if timestamps.tz is None:
        raise ValueError("timestamps must be timezone-aware")
    ann = fomc_announcements().tz_convert(timestamps.tz)
    ts = timestamps.as_unit("ns").asi8
    starts, ends = (ann - window).as_unit("ns").asi8, (ann + window).as_unit("ns").asi8
    k = np.searchsorted(starts, ts, side="right") - 1
    return (k >= 0) & (ts <= ends[np.clip(k, 0, None)])
