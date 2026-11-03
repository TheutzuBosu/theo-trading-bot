"""Tests for the minute-by-minute intraday engine (offline: synthetic bars + the SPY fixture)."""

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from src.backtest.intraday_engine import (
    IntradayConfig,
    IntradayPanel,
    IntradaySignals,
    run_intraday,
)
from tests.bt_helpers import minute_bars, minute_signals

FIXTURE = Path(__file__).parent / "fixtures" / "minute_spy_sip_2016-11.csv"
C = 0.015  # stock cost per side: half spread 0.005 + slippage 0.01 (D25)

# a quiet up-drifting morning; the tests put signals on these rows
ROWS = [
    (100.00, 100.20, 99.90, 100.10),
    (100.10, 100.30, 100.00, 100.20),
    (100.25, 100.50, 100.20, 100.40),
    (100.40, 100.60, 100.30, 100.50),
    (100.50, 100.70, 100.40, 100.60),
]


def run(frames, signals, **config):
    panel = IntradayPanel.from_frames(frames)
    return run_intraday(
        panel, IntradaySignals.from_frames(signals, panel), IntradayConfig(**config)
    )


def one(rows, entries=None, symbol="SPY", **columns):
    bars = minute_bars(rows)
    return {symbol: bars}, {symbol: minute_signals(bars.index, entries, **columns)}


def test_panel_sessions_from_fixture():
    df = pd.read_csv(FIXTURE, index_col=0)
    df.index = pd.to_datetime(df.index, utc=True).tz_convert("America/New_York")
    panel = IntradayPanel.from_frames({"SPY": df})
    assert list(panel.sessions.strftime("%Y-%m-%d")) == ["2016-11-23", "2016-11-25"]
    last = panel.timestamps[panel.last_bar[:, 0]]
    assert list(last.strftime("%H:%M")) == ["15:59", "12:59"]  # 25 Nov closes at 13:00


def test_entry_at_next_open_and_exit_at_session_close():
    # signal on the close of row 1 -> buy at the Open of row 2; the last bar exits at its Close
    res = run(*one(ROWS, {1: (1, 99.0)}))
    t = res.trades.iloc[0]
    assert t["entry_time"] == res.trades["signal_time"].iloc[0] + pd.Timedelta(minutes=1)
    assert t["entry_open"] == 100.25 and t["entry_price"] == pytest.approx(100.25 + C)
    assert t["qty"] == pytest.approx(2.0)  # 0.5% of 500 / risk 1.25
    assert t["exit_reason"] == "eod" and t["exit_price"] == pytest.approx(100.60 - C)
    assert t["pnl"] == pytest.approx(2 * (100.60 - C - 100.25 - C))
    assert t["r_multiple"] == pytest.approx((0.35 - 2 * C) / 1.25)
    assert t["mae_r"] == pytest.approx(-0.05 / 1.25) and t["mfe_r"] == pytest.approx(0.45 / 1.25)
    assert t["risk_pct"] == pytest.approx(0.005)
    assert res.equity.iloc[-1] == pytest.approx(500 + t["pnl"])


def test_fixture_early_close_exit_and_no_overnight_orders():
    df = pd.read_csv(FIXTURE, index_col=0)
    df.index = pd.to_datetime(df.index, utc=True).tz_convert("America/New_York")
    entries = {389: (1, 200.0), 390 + 100: (1, 200.0)}  # last bar of 23 Nov; 11:10 on 25 Nov
    res = run({"SPY": df}, {"SPY": minute_signals(df.index, entries)})
    assert len(res.trades) == 1  # the signal on 23 Nov 15:59 never fills on 25 Nov
    t = res.trades.iloc[0]
    assert t["entry_time"] == pd.Timestamp("2016-11-25 11:11", tz="America/New_York")
    assert t["exit_time"] == pd.Timestamp("2016-11-25 12:59", tz="America/New_York")
    assert t["exit_raw"] == pytest.approx(df["close"].iloc[-1])


def test_stop_hit_intrabar_exits_at_stop():
    rows = ROWS[:3] + [(100.40, 100.45, 99.80, 99.95)] + ROWS[4:]
    res = run(*one(rows, {1: (1, 100.0)}))
    t = res.trades.iloc[0]
    assert t["exit_reason"] == "stop" and t["exit_raw"] == 100.0
    assert t["r_multiple"] == pytest.approx((100.0 - C - 100.25 - C) / 0.25)
    assert t["mae_r"] == pytest.approx(-1.0)


def test_gap_through_stop_exits_at_open():
    rows = ROWS[:3] + [(99.70, 99.80, 99.60, 99.75)] + ROWS[4:]
    t = run(*one(rows, {1: (1, 100.0)})).trades.iloc[0]
    assert t["exit_reason"] == "stop_gap" and t["exit_raw"] == 99.70 and t["exit_at_open"]


def test_stop_and_target_in_same_bar_stop_wins():
    rows = ROWS[:3] + [(100.40, 101.50, 99.80, 100.00)] + ROWS[4:]
    t = run(*one(rows, {1: (1, 100.0)}, target={1: 101.0})).trades.iloc[0]
    assert t["exit_reason"] == "stop"


def test_target_exit():
    t = run(*one(ROWS, {1: (1, 99.0)}, target={1: 100.55})).trades.iloc[0]
    assert t["exit_reason"] == "target" and t["exit_raw"] == 100.55


def test_partial_target_then_rest_at_close():
    res = run(*one(ROWS, {1: (1, 99.0)}, target={1: 100.55}), target_fraction=0.5)
    assert len(res.trades) == 1
    t = res.trades.iloc[0]
    assert t["partial_exit"] and t["exit_reason"] == "eod"
    assert t["exit_raw"] == pytest.approx((100.55 + 100.60) / 2)
    assert t["pnl"] == pytest.approx(1 * (100.55 - C) + 1 * (100.60 - C) - 2 * (100.25 + C))


def test_trailing_stop_only_tightens():
    rows = ROWS[:4] + [(100.50, 100.70, 100.25, 100.60)]
    # row 2 raises the stop to 100.28, row 3 asks for 99.0 (wider: ignored); row 4 low 100.25
    res = run(*one(rows, {1: (1, 99.0)}, stop_long={2: 100.28, 3: 99.0}))
    t = res.trades.iloc[0]
    assert t["exit_reason"] == "stop" and t["stop"] == 100.28 and t["initial_stop"] == 99.0
    assert t["exit_time"] == res.trades["entry_time"].iloc[0] + pd.Timedelta(minutes=2)


def test_exit_signal_fills_next_open():
    t = run(*one(ROWS, {1: (1, 99.0)}, exit={2: True})).trades.iloc[0]
    assert t["exit_reason"] == "signal" and t["exit_raw"] == 100.40


def test_short_trade():
    rows = [(100.0, 100.1, 99.8, 99.9), (99.9, 100.0, 99.7, 99.8), (99.75, 99.8, 99.5, 99.6)]
    t = run(*one(rows, {0: (-1, 101.0)})).trades.iloc[0]
    assert t["direction"] == "short"
    assert t["entry_price"] == pytest.approx(99.9 - C)
    assert t["exit_price"] == pytest.approx(99.6 + C)
    risk = 101.0 - 99.9
    assert t["qty"] == pytest.approx(0.005 * 500 / risk)
    assert t["r_multiple"] == pytest.approx((99.9 - C - 99.6 - C) / risk)
    assert t["mfe_r"] == pytest.approx((99.9 - 99.5) / risk)


def test_long_only_rejects_shorts():
    res = run(*one(ROWS, {1: (-1, 101.0)}), long_only=True)
    assert res.trades.empty and list(res.rejections["reason"]) == ["long_only"]


def test_entry_checks():
    res = run(*one(ROWS, {0: (1, 100.20), 2: (1, 100.36)}))  # stop above Open; risk 0.04 < 0.06
    assert res.trades.empty
    assert list(res.rejections["reason"]) == ["stop_through_open", "risk_below_cost"]


def test_one_position_per_symbol():
    res = run(*one(ROWS, {1: (1, 99.0), 2: (1, 99.0)}))
    assert len(res.trades) == 1 and list(res.rejections["reason"]) == ["position_open"]


def test_volatility_target_size_capped_by_exposure():
    t = run(*one(ROWS, {1: (1, 99.0)}, size={1: 3.0})).trades.iloc[0]
    assert t["notional_pct"] == pytest.approx(2.0)  # 3x wanted, 2x equity allowed
    assert t["risk_pct"] == pytest.approx(1000 / 100.25 * 1.25 / 500)
    t = run(*one(ROWS, {1: (1, 99.0)}, size={1: 3.0}), max_exposure=1.0).trades.iloc[0]
    assert t["notional_pct"] == pytest.approx(1.0)
    t = run(*one(ROWS, {1: (1, 99.0)}, size={1: 3.0}), max_risk_per_trade=0.005).trades.iloc[0]
    assert t["risk_pct"] == pytest.approx(0.005)


def test_exposure_cap_across_symbols_and_whole_shares():
    a, b = minute_bars(ROWS), minute_bars(ROWS)
    sig = {s: minute_signals(a.index, {1: (1, 99.0)}, size={1: 1.5}) for s in ("QQQ", "SPY")}
    res = run({"QQQ": a, "SPY": b}, sig)
    assert list(res.trades["notional_pct"]) == pytest.approx([1.5, 0.5], abs=1e-3)
    res = run({"QQQ": a, "SPY": b}, sig, whole_shares=True)
    assert list(res.trades["qty"]) == [7.0, 2.0]  # floor(750 / 100.25), floor(~298 / 100.25)


def test_symbol_with_missing_bars_exits_at_its_last_bar():
    a, b = minute_bars(ROWS), minute_bars(ROWS[:3])  # SPY data stops after 3 bars (D26)
    sig = {"SPY": minute_signals(b.index, {0: (1, 99.0)})}
    t = run({"QQQ": a, "SPY": b}, sig).trades.iloc[0]
    assert t["exit_reason"] == "eod" and t["exit_time"] == b.index[-1] and t["exit_raw"] == 100.40


def test_fomc_veto():
    rows = ROWS * 20  # 13:00-14:39 on an FOMC day (statement at 14:00)
    bars = minute_bars(rows, start="2016-11-02 13:00")
    entries = {29: (1, 99.0), 30: (1, 99.0), 90: (1, 99.0)}  # fill at 13:30, 13:31, 14:31
    sig = {"SPY": minute_signals(bars.index, entries, exit={30: True, 31: True})}
    res = run({"SPY": bars}, sig)
    assert list(res.rejections["reason"]) == ["fomc", "fomc"]
    assert list(res.trades["entry_time"].dt.strftime("%H:%M")) == ["14:31"]
    res = run({"SPY": bars}, sig, fomc_veto=False)
    assert len(res.trades) == 3


def test_costs_cfd_and_stress():
    t = run(*one(ROWS, {1: (1, 99.0)}), cost_variant="cfd").trades.iloc[0]
    assert t["entry_price"] == pytest.approx(100.25 + 0.08)
    t = run(*one(ROWS, {1: (1, 99.0)}), cost_stress=1.5).trades.iloc[0]
    assert t["entry_price"] == pytest.approx(100.25 + 1.5 * C)


def test_window_and_daily_equity():
    day1 = minute_bars(ROWS, start="2026-01-05 09:30")
    day2 = minute_bars(ROWS, start="2026-01-06 09:30")
    bars = pd.concat([day1, day2])
    sig = {"SPY": minute_signals(bars.index, {1: (1, 99.0), 6: (1, 99.0)})}
    res = run({"SPY": bars}, sig)
    assert len(res.equity) == 2 and len(res.trades) == 2
    assert np.diff(res.equity.to_numpy())[0] == pytest.approx(res.trades["pnl"].iloc[1])
    panel = IntradayPanel.from_frames({"SPY": bars})
    one_day = run_intraday(panel, IntradaySignals.from_frames(sig, panel), start="2026-01-06")
    assert len(one_day.equity) == 1 and len(one_day.trades) == 1


def test_exit_long_exit_short_and_flip_at_same_open():
    # Enter long at row 1 (fills at row 2 Open=100.25); row 2 exit_short (ignored for long);
    # row 3 exit_long + short entry -> at row 4 Open=100.50 long exits and short enters
    res = run(
        *one(
            ROWS,
            entries={1: (1, 99.0), 3: (-1, 102.0)},
            exit_short={2: True},
            exit_long={3: True},
        )
    )
    assert len(res.trades) == 2
    t0, t1 = res.trades.iloc[0], res.trades.iloc[1]
    assert t0["direction"] == "long" and t0["exit_reason"] == "signal"
    assert t0["exit_time"] == t1["entry_time"]
    assert t0["exit_raw"] == 100.50 and t1["entry_open"] == 100.50
    assert t1["direction"] == "short" and t1["exit_reason"] == "eod"


def test_stop_after_target_tightens_after_partial_exit():
    # Row 1 signals long, initial stop 99.0, target 100.45 (hit on row 2 High=100.50),
    # stop_after_target=100.35 -> row 3 has Low=100.30 so remaining 50% exits at 100.35 stop
    res = run(
        *one(
            ROWS,
            entries={1: (1, 99.0)},
            target={1: 100.45},
            stop_after_target={1: 100.35},
        ),
        target_fraction=0.5,
    )
    t = res.trades.iloc[0]
    assert t["partial_exit"] and t["exit_reason"] == "stop"
    assert t["stop"] == pytest.approx(100.35)
    assert t["exit_raw"] == pytest.approx((100.45 + 100.35) / 2)
