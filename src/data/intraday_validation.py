"""Validation of 1-minute session bars against the NYSE calendar (Faza B, B1)."""

from __future__ import annotations

import pandas as pd

from src.data.intraday import nyse_sessions


def expected_bars(sessions: pd.DataFrame) -> pd.Series:
    """Number of 1-minute bars in each session (390 normally, 210 on a 13:00 early close)."""
    minutes = (sessions["close"] - sessions["open"]).dt.total_seconds() // 60
    return minutes.astype(int)


def validate_minute_bars(
    df: pd.DataFrame,
    start: str | None = None,
    end: str | None = None,
    min_fill: float = 0.95,
) -> dict:
    """Check session bars against the NYSE calendar; returns a report (never raises on gaps).

    Report keys:
    - sessions / days_with_bars / bars
    - missing_days: calendar sessions without any bar
    - extra_days: days with bars that are not sessions
    - short_sessions: {day: [bars, expected]} for days with fewer than min_fill * expected bars
    - early_closes: calendar half days in the range (expected 210 bars)
    - duplicates: repeated timestamps
    - outside_session: bars outside open <= t < close
    - bad_ohlc: rows where high/low do not bound open/close, or prices <= 0, or volume < 0
    """
    if df.empty:
        raise ValueError("no bars to validate")
    idx = df.index
    days = pd.DatetimeIndex(idx.date)
    start = start or days.min()
    end = end or days.max()
    sessions = nyse_sessions(start, end)
    expected = expected_bars(sessions)

    counts = pd.Series(1, index=days).groupby(level=0).sum()
    missing = sessions.index.difference(counts.index)
    extra = counts.index.difference(sessions.index)
    common = counts.index.intersection(sessions.index)
    fill = counts[common] / expected[common]
    short = fill[fill < min_fill].index

    opens = pd.DatetimeIndex(sessions["open"].reindex(days))
    closes = pd.DatetimeIndex(sessions["close"].reindex(days))
    in_session = (idx >= opens) & (idx < closes)

    hi_ok = (df["high"] >= df[["open", "close", "low"]].max(axis=1)) & (
        df["low"] <= df[["open", "close"]].min(axis=1)
    )
    positive = (df[["open", "high", "low", "close"]] > 0).all(axis=1) & (df["volume"] >= 0)

    def _fmt(d) -> str:
        return pd.Timestamp(d).date().isoformat()

    return {
        "sessions": int(len(sessions)),
        "days_with_bars": int(len(counts)),
        "bars": int(len(df)),
        "missing_days": [_fmt(d) for d in missing],
        "extra_days": [_fmt(d) for d in extra],
        "short_sessions": {_fmt(d): [int(counts[d]), int(expected[d])] for d in short},
        "early_closes": [_fmt(d) for d in expected[expected < 390].index],
        "duplicates": int(idx.duplicated().sum()),
        "outside_session": int((~in_session).sum()),
        "bad_ohlc": int((~(hi_ok & positive)).sum()),
    }


def is_clean(report: dict) -> bool:
    """True when nothing is missing, duplicated, outside the session or inconsistent."""
    return not (
        report["missing_days"]
        or report["extra_days"]
        or report["short_sessions"]
        or report["duplicates"]
        or report["outside_session"]
        or report["bad_ohlc"]
    )
