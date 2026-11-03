"""Tests for the Faza B metrics, the random-direction test and the minute look-ahead check."""

import math
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from src.backtest.intraday_engine import (
    SIGNAL_COLUMNS,
    IntradayConfig,
    IntradayPanel,
    IntradaySignals,
    run_intraday,
)
from src.backtest.intraday_metrics import (
    deflated_sharpe,
    direction_outcomes,
    r_stats,
    random_direction_test,
    summarize_intraday,
    yearly_returns,
)
from src.backtest.lookahead import find_lookahead
from tests.bt_helpers import minute_bars, minute_signals

FIXTURE = Path(__file__).parent / "fixtures" / "minute_spy_sip_2016-11.csv"
ROWS = [
    (100.00, 100.20, 99.90, 100.10),
    (100.10, 100.30, 100.00, 100.20),
    (100.25, 100.50, 100.20, 100.40),
    (100.40, 100.60, 100.30, 100.50),
    (100.50, 100.70, 100.40, 100.60),
]


def test_r_stats_by_hand():
    s = r_stats([1.0, -1.0, 2.0, 0.0])
    assert s["expectancy_r"] == 0.5
    assert s["std_r"] == pytest.approx(math.sqrt(5 / 3))
    assert s["t_stat"] == pytest.approx(0.5 / (math.sqrt(5 / 3) / 2))
    assert s["p_value"] == pytest.approx(0.2193, abs=1e-4)
    assert s["p_bonferroni"] == 1.0  # 9 x 0.22, capped
    assert math.isnan(r_stats([0.3])["t_stat"])


def test_deflated_sharpe():
    rng = np.random.default_rng(1)
    x = rng.normal(0.0005, 0.01, 1001)
    d9, d1 = deflated_sharpe(x, n_trials=9), deflated_sharpe(x, n_trials=1)
    assert d9["sr0"] == pytest.approx(1.52078 / math.sqrt(1000), rel=1e-4)  # E[max] of 9 trials
    assert d1["sr0"] == 0.0 and d9["dsr"] < d1["dsr"]
    strong = rng.normal(0.003, 0.01, 2520)  # Sharpe ~4.8 a year
    assert deflated_sharpe(strong)["dsr"] > 0.999
    assert deflated_sharpe(rng.normal(0.0, 0.01, 2520))["dsr"] < 0.5


def test_yearly_returns():
    eq = pd.Series(
        [550.0, 500.0, 600.0], index=pd.to_datetime(["2020-06-01", "2020-12-31", "2021-12-31"])
    )
    assert yearly_returns(eq, 500.0).tolist() == pytest.approx([0.0, 0.2])


def _run(rows, entries, **config):
    bars = minute_bars(rows)
    panel = IntradayPanel.from_frames({"SPY": bars})
    signals = IntradaySignals.from_frames({"SPY": minute_signals(bars.index, entries)}, panel)
    cfg = IntradayConfig(**config)
    return panel, cfg, run_intraday(panel, signals, cfg)


def test_summarize_intraday():
    _, _, res = _run(ROWS, {1: (1, 99.0)})
    s = summarize_intraday(res)
    assert s["n_trades"] == 1 and s["n_long"] == 1 and s["n_short"] == 0
    assert s["expectancy_r"] == pytest.approx(0.256)
    assert s["loss_days_2pct"] == 0 and s["pct_years_positive"] == 1.0
    assert s["avg_risk_pct"] == pytest.approx(0.005)


def test_direction_outcomes_by_hand():
    panel, cfg, res = _run(ROWS, {1: (1, 99.0)})
    out = direction_outcomes(res.trades, panel, cfg).iloc[0]
    assert out["r_long"] == pytest.approx(res.trades["r_multiple"].iloc[0])  # same trade replayed
    assert out["r_short"] == pytest.approx((-0.35 - 0.03) / 1.25)  # mirrored stop 101.5 never hit
    assert out["r_own"] == out["r_long"]
    panel, cfg, res = _run(ROWS, {1: (1, 99.95)})  # risk 0.30: the short stop 100.55 is hit
    out = direction_outcomes(res.trades, panel, cfg).iloc[0]
    assert out["r_long"] == pytest.approx((0.35 - 0.03) / 0.30)
    assert out["r_short"] == pytest.approx((-0.30 - 0.03) / 0.30)


def test_replay_ignores_the_real_exit():
    # the short (risk 0.50) is stopped at 100.75 on row 3; both replays run to the session close
    rows = ROWS[:3] + [(100.40, 100.80, 100.15, 100.30), ROWS[4]]
    panel, cfg, res = _run(rows, {1: (-1, 100.75)})
    t = res.trades.iloc[0]
    assert t["exit_reason"] == "stop" and t["exit_bar"] == 3
    out = direction_outcomes(res.trades, panel, cfg).iloc[0]
    assert out["r_short"] == pytest.approx(t["r_multiple"]) and out["r_own"] == out["r_short"]
    assert out["r_long"] == pytest.approx((100.60 - 100.25 - 0.03) / 0.50)  # not the 100.75 exit


def test_random_direction_test():
    perfect = pd.DataFrame({"r_long": [1.0] * 200, "r_short": [-1.0] * 200})
    perfect["r_own"] = 1.0
    s = random_direction_test(perfect).summary()
    assert s["n_runs"] == 1000 and s["pct_beaten"] == 1.0 and abs(s["random_p50"]) < 0.1
    assert s["actual_expectancy_r"] == 1.0
    again = random_direction_test(perfect).summary()
    assert again == s  # seeded
    noise = pd.DataFrame({"r_long": np.r_[[1.0] * 100, [-1.0] * 100], "r_short": [0.0] * 200})
    assert random_direction_test(noise, actual=0.0).summary()["pct_beaten"] < 0.95


def test_random_direction_long_only():
    # candidates of a long+short run; the long-only strategy took the first 50 (all winners)
    candidates = pd.DataFrame({"r_long": np.r_[[2.0] * 50, [-1.0] * 150], "r_short": 0.0})
    s = random_direction_test(candidates, actual=2.0, long_only=True).summary()
    assert s["pct_beaten"] == 1.0 and s["random_p50"] == pytest.approx(-0.25, abs=0.15)
    s = random_direction_test(candidates, actual=-0.25, long_only=True).summary()
    assert s["pct_beaten"] < 0.95
    with pytest.raises(ValueError):
        random_direction_test(candidates, long_only=True)


def _fixture() -> dict:
    df = pd.read_csv(FIXTURE, index_col=0)
    df.index = pd.to_datetime(df.index, utc=True).tz_convert("America/New_York")
    return {"SPY": df}


def _momentum(peek: bool):
    def strategy(prices):
        out = {}
        for sym, df in prices.items():
            close = df["close"].shift(-1) if peek else df["close"]
            up = close > close.rolling(5).mean()
            out[sym] = pd.DataFrame({"entry": up.astype(int), "stop": close - 0.5}, index=df.index)
        return out

    return strategy


def test_lookahead_check_on_minute_bars():
    prices = _fixture()
    assert find_lookahead(_momentum(False), prices, n_checks=5, columns=SIGNAL_COLUMNS) == []
    problems = find_lookahead(_momentum(True), prices, n_checks=5, columns=SIGNAL_COLUMNS)
    assert problems and "2016-11-" in problems[0] and ":" in problems[0]
