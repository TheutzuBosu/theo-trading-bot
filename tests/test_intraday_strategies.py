"""Offline unit and look-ahead tests for D1, D1b, and D2 intraday strategies (B3.2, D29/D29b)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from src.backtest.intraday_engine import (
    SIGNAL_COLUMNS,
    IntradayPanel,
    IntradaySignals,
    run_intraday,
)
from src.backtest.lookahead import assert_no_lookahead
from src.strategies.intraday_d1 import (
    D1bParams,
    D1Params,
    compute_noise_bands,
    generate_d1_signals,
    generate_d1b_signals,
)
from src.strategies.intraday_d2 import generate_d2_signals

FIXTURE = Path(__file__).parent / "fixtures" / "minute_spy_sip_2016-11.csv"


def _make_multiday_bars(
    dates: list[str],
    n_minutes: int = 390,
    base_price: float = 500.0,
) -> pd.DataFrame:
    """Build synthetic regular-session 1-minute bars across multiple trading days."""
    frames = []
    for d_idx, d in enumerate(dates):
        idx = pd.date_range(
            pd.Timestamp(f"{d} 09:30", tz="America/New_York"),
            periods=n_minutes,
            freq="min",
        )
        # Small deterministic daily variation so daily returns have non-zero volatility
        day_open = base_price * (1.0 + 0.002 * ((d_idx % 3) - 1))
        mins = np.arange(n_minutes, dtype=float)
        # Normal days move +-0.10% around open; last day breaks out strongly
        if d_idx < len(dates) - 1:
            close = day_open * (1.0 + 0.001 * np.sin(mins / 20.0))
        else:
            close = day_open * (1.0 + 0.008 * (mins / max(n_minutes - 1, 1)))
        open_ = np.r_[day_open, close[:-1]]
        high = np.maximum(open_, close) + 0.10
        low = np.minimum(open_, close) - 0.10
        df = pd.DataFrame(
            {
                "open": open_,
                "high": high,
                "low": low,
                "close": close,
                "volume": 10_000.0,
                "vwap": (open_ + close) / 2.0,
            },
            index=idx,
        )
        frames.append(df)
    return pd.concat(frames)


def test_noise_bands_gap_adjustment_and_formula():
    # 3 sessions with lookback=2:
    # Day 0: Open=100, Close at 09:59 is 101 (|move|=0.01), ends at 101
    # Day 1: Open=100, Close at 09:59 is 103 (|move|=0.03), ends at 102
    # Day 2: Open=104 (gap up above prev Close=102) -> upper_ref=104, lower_ref=102, sigma=0.02
    dates = ["2026-01-05", "2026-01-06", "2026-01-07"]
    df = _make_multiday_bars(dates, n_minutes=60, base_price=100.0)
    # Override exact values on the 3 days
    for d_idx, (d_open, c_959, c_end) in enumerate(
        [(100.0, 101.0, 101.0), (100.0, 103.0, 102.0), (104.0, 108.0, 108.0)]
    ):
        sl = slice(d_idx * 60, (d_idx + 1) * 60)
        df.iloc[sl, df.columns.get_loc("open")] = d_open
        df.iloc[sl, df.columns.get_loc("close")] = d_open
        df.iloc[d_idx * 60 + 29, df.columns.get_loc("close")] = c_959
        df.iloc[d_idx * 60 + 59, df.columns.get_loc("close")] = c_end

    bands = compute_noise_bands(df, lookback=2, mult=1.0)
    row_day2_959 = bands.iloc[2 * 60 + 29]
    assert row_day2_959["sigma"] == pytest.approx(0.02)
    assert row_day2_959["ub"] == pytest.approx(104.0 * 1.02)
    assert row_day2_959["lb"] == pytest.approx(102.0 * 0.98)


def test_d1_check_times_and_missing_bar_fallback():
    # Load the 2-session fixture (2016-11-23 full day, 2016-11-25 early close at 13:00)
    df = pd.read_csv(FIXTURE, index_col=0)
    df.index = pd.to_datetime(df.index, utc=True).tz_convert("America/New_York")
    sig = generate_d1_signals(df, D1Params(lookback=1, vol_lookback=2))
    assert all(col in sig.columns for col in SIGNAL_COLUMNS)

    # On day 2 (2016-11-25, early close at 13:00), checks only run from 09:59 to 12:29 (6 checks)
    day2 = sig.loc["2016-11-25"]
    active = day2.index[(day2["entry"] != 0) | day2["exit_long"] | day2["exit_short"]]
    assert [ts.strftime("%H:%M") for ts in active] == [
        "09:59",
        "10:29",
        "10:59",
        "11:29",
        "11:59",
        "12:29",
    ]

    # Drop the 10:29 bar on 2016-11-25 -> fallback uses 10:28 (D26)
    dropped = df.drop(pd.Timestamp("2016-11-25 10:29:00", tz="America/New_York"))
    sig_drop = generate_d1_signals(dropped, D1Params(lookback=1, vol_lookback=2)).loc["2016-11-25"]
    active_drop = sig_drop.index[
        (sig_drop["entry"] != 0) | sig_drop["exit_long"] | sig_drop["exit_short"]
    ]
    assert "10:28" in [ts.strftime("%H:%M") for ts in active_drop]


def test_d1_entry_and_trailing_exit_in_engine():
    dates = [f"2026-01-{d:02d}" for d in (5, 6, 7, 8, 9)]
    df = _make_multiday_bars(dates, n_minutes=120, base_price=500.0)
    sig = generate_d1_signals(df, D1Params(lookback=3, vol_lookback=3))
    entries = sig[sig["entry"] == 1]
    assert len(entries) >= 1
    first_sig = entries.iloc[0]
    assert first_sig["stop"] < df.loc[entries.index[0], "close"]
    assert 0.0 < first_sig["size"] <= 0.5
    assert "D1(" in first_sig["entry_reason"]

    panel = IntradayPanel.from_frames({"SPY": df})
    res = run_intraday(panel, IntradaySignals.from_frames({"SPY": sig}, panel))
    assert len(res.trades) >= 1


def test_d1b_check_times_ladder_and_time_exit():
    # 6 sessions so L=4 noise bands and L=4 daily volatility are populated on day 5
    dates = [f"2026-01-{d:02d}" for d in (5, 6, 7, 8, 9, 12)]
    df = _make_multiday_bars(dates, n_minutes=390, base_price=500.0)
    params = D1bParams()
    sig = generate_d1b_signals(df, params)

    last_day = sig.loc["2026-01-12"]
    # Time exit must fire on the 15:29 bar (so position closes at 15:30 Open)
    exit_times = last_day.index[last_day["exit"]]
    assert [ts.strftime("%H:%M") for ts in exit_times] == ["15:29"]

    entries = last_day[last_day["entry"] == 1]
    assert len(entries) >= 1
    ts0 = entries.index[0]
    assert ts0.strftime("%H:%M") in {
        "10:11",
        "10:57",
        "11:43",
        "12:29",
        "13:15",
        "14:01",
        "14:47",
    }
    # When sigma_d <= 0.025, r = 0.005 * Close, target = Close * (1 + 2.2 * 0.005) = Close * 1.011
    c0 = df.loc[ts0, "close"]
    assert entries.loc[ts0, "target"] == pytest.approx(c0 * 1.011)
    assert entries.loc[ts0, "stop_after_target"] >= c0 * (1.0 - 0.0014)


def test_d2_orb_long_short_doji_and_10r_target():
    # Day 1: bullish ORB (Open=100 at 09:30, Low=99.5, Close=100.5 at 09:34 -> target=110.5)
    # Day 2: doji ORB (Open=100.0, Close=100.005 -> |diff|=0.005% <= 0.01% -> no trade)
    # Day 3: bearish ORB (Open=100.0, High=100.6, Close=99.6 at 09:34 -> risk=1.0, target=89.6)
    df = _make_multiday_bars(
        ["2026-01-05", "2026-01-06", "2026-01-07"], n_minutes=30, base_price=100.0
    )
    df["open"] = 100.0
    df["high"] = 100.2
    df["low"] = 99.8
    df["close"] = 100.0

    # Day 1 (rows 0..29)
    df.iloc[2, df.columns.get_loc("low")] = 99.5
    df.iloc[4, df.columns.get_loc("close")] = 100.5
    # Day 2 (rows 30..59): doji at row 34
    df.iloc[34, df.columns.get_loc("close")] = 100.005
    # Day 3 (rows 60..89): bearish at row 64
    df.iloc[61, df.columns.get_loc("high")] = 100.6
    df.iloc[64, df.columns.get_loc("close")] = 99.6

    sig = generate_d2_signals(df)
    assert sig.iloc[4]["entry"] == 1
    assert sig.iloc[4]["stop"] == pytest.approx(99.5)
    assert sig.iloc[4]["target"] == pytest.approx(100.5 + 10.0 * 1.0)
    assert sig.iloc[4]["size"] == pytest.approx(0.5)

    assert (sig.iloc[30:60]["entry"] == 0).all()

    assert sig.iloc[64]["entry"] == -1
    assert sig.iloc[64]["stop"] == pytest.approx(100.6)
    assert sig.iloc[64]["target"] == pytest.approx(99.6 - 10.0 * 1.0)


def test_intraday_strategies_no_lookahead_on_fixture():
    df = pd.read_csv(FIXTURE, index_col=0)
    df.index = pd.to_datetime(df.index, utc=True).tz_convert("America/New_York")
    prices = {"SPY": df}

    assert_no_lookahead(
        lambda p: {
            s: generate_d1_signals(d, D1Params(lookback=1, vol_lookback=2)) for s, d in p.items()
        },
        prices,
        n_checks=8,
        min_history=60,
        columns=SIGNAL_COLUMNS,
    )
    assert_no_lookahead(
        lambda p: {s: generate_d1b_signals(d, D1bParams(lookback=1)) for s, d in p.items()},
        prices,
        n_checks=8,
        min_history=60,
        columns=SIGNAL_COLUMNS,
    )
    assert_no_lookahead(
        lambda p: {s: generate_d2_signals(d) for s, d in p.items()},
        prices,
        n_checks=8,
        min_history=10,
        columns=SIGNAL_COLUMNS,
    )


def test_intraday_strategies_no_lookahead_multiday_active_signals():
    dates = [f"2026-01-{d:02d}" for d in (5, 6, 7, 8, 9, 12)]
    df = _make_multiday_bars(dates, n_minutes=120, base_price=500.0)
    prices = {"SPY": df}

    assert_no_lookahead(
        lambda p: {
            s: generate_d1_signals(d, D1Params(lookback=3, vol_lookback=3)) for s, d in p.items()
        },
        prices,
        n_checks=6,
        min_history=400,
        columns=SIGNAL_COLUMNS,
    )
    assert_no_lookahead(
        lambda p: {s: generate_d1b_signals(d) for s, d in p.items()},
        prices,
        n_checks=6,
        min_history=600,
        columns=SIGNAL_COLUMNS,
    )
