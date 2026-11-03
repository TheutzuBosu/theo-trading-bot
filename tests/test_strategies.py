"""Strategy tests on hand-built scenarios (small parameters, every value checkable by hand)."""

import numpy as np
import pandas as pd
import pytest
from pydantic import ValidationError

from src.backtest.engine import BacktestConfig
from src.backtest.lookahead import assert_no_lookahead
from src.backtest.walkforward import backtest_strategy
from src.strategies import MODULES, load_params, load_strategy
from src.strategies import s1_trend_breakout as s1
from src.strategies import s2_momentum_rotation as s2
from src.strategies import s3_rsi2_pullback as s3
from src.strategies import s4_macd_ema200 as s4
from tests.bt_helpers import random_walk


def from_closes(closes, start="2026-01-05"):
    """Bars with Open = Close, High = Close + 0.5, Low = Close - 0.5."""
    close = np.asarray(closes, dtype=float)
    df = pd.DataFrame({"open": close, "high": close + 0.5, "low": close - 0.5, "close": close})
    df.index = pd.bdate_range(start, periods=len(df))
    df["volume"] = 1_000_000.0
    return df


def spy_trend(n, step, start="2026-01-05"):
    return from_closes(400 + step * np.arange(n), start)


# --- S1 Trend Breakout ---------------------------------------------------------------

S1_SMALL = s1.Params(sma_filter=3, entry_lookback=3, exit_lookback=2, atr_period=2, stop_atr=2.5)
S1_CLOSES = [10, 10, 10, 10, 10, 12, 12.2, 11, 9]


def test_s1_breakout_entry_exit_and_stop():
    out = s1.signals({"AAA": from_closes(S1_CLOSES), "SPY": spy_trend(9, 1.0)}, S1_SMALL)["AAA"]
    # bar 5: Close 12 > max High of bars 2..4 (10.5), > SMA3 10.67, SPY rising
    assert out["entry"].tolist() == [False] * 5 + [True] + [False] * 3
    # bar 7: Close 11 < min Low of bars 5..6 (11.5); bar 8: 9 < 10.5
    assert out["exit"].tolist() == [False] * 7 + [True, True]
    # TR = 1 then 1, 1, 1, 1, then 2.5 on bar 5; ATR2 on bar 5 = (1 + 2.5)/2 = 1.75 -> 2.5 * 1.75
    assert out["stop_distance"].iloc[5] == pytest.approx(4.375)
    assert out["entry_reason"].iloc[5].startswith("S1 Trend Breakout: Close 12.00 > maximul pe 3")
    assert out["entry_reason"].iloc[4] == ""


def test_s1_no_entry_when_spy_below_its_sma():
    out = s1.signals({"AAA": from_closes(S1_CLOSES), "SPY": spy_trend(9, -1.0)}, S1_SMALL)["AAA"]
    assert not out["entry"].any()


def test_s1_requires_spy_and_does_not_trade_it():
    with pytest.raises(ValueError, match="SPY"):
        s1.signals({"AAA": from_closes(S1_CLOSES)}, S1_SMALL)
    out = s1.signals({"AAA": from_closes(S1_CLOSES), "SPY": spy_trend(9, 1.0)}, S1_SMALL)
    assert set(out) == {"AAA"}


# --- S2 Momentum Rotation ------------------------------------------------------------

S2_SMALL = s2.Params(
    momentum_lookback=3,
    momentum_skip=1,
    sma_filter=2,
    top_n=2,
    exit_rank=3,
    atr_period=2,
    stop_atr=3.0,
)


def _growth(daily_rates, start="2026-01-26"):
    """Close compounding at daily_rates[i] on bar i (first close 100)."""
    close = 100 * np.cumprod(1 + np.asarray(daily_rates, dtype=float))
    return from_closes(close, start)


def _s2_universe(spy_step=1.0):
    # 2026-01-26 .. 2026-03-06: Feb 2 is bar 5, Mar 2 is bar 25 (first trading days)
    n = 30
    feb, mar = 5, 25
    rates = {"AAA": [0.03] * n, "BBB": [0.02] * n, "CCC": [0.01] * n, "DDD": [0.005] * n}
    rates["EEE"] = [-0.01] * n  # falling: Close < SMA2, never eligible
    rates["AAA"] = [0.03] * (feb + 1) + [-0.02] * (n - feb - 1)  # AAA turns down in February
    rates["CCC"] = [0.01] * (feb + 1) + [0.05] * (n - feb - 1)  # CCC becomes the leader
    prices = {s: _growth(r) for s, r in rates.items()}
    prices["SPY"] = spy_trend(n, spy_step, "2026-01-26")
    return prices, feb, mar


def test_s2_first_trading_days():
    flags = s2.first_trading_days(pd.bdate_range("2026-01-26", periods=30))
    assert flags[flags].index.strftime("%Y-%m-%d").tolist() == ["2026-02-02", "2026-03-02"]


def test_s2_monthly_rotation():
    prices, feb, mar = _s2_universe()
    out = s2.signals(prices, S2_SMALL)
    entries = {s: f.index[f["entry"]].tolist() for s, f in out.items()}
    exits = {s: f.index[f["exit"]].tolist() for s, f in out.items()}
    d_feb, d_mar = prices["SPY"].index[feb], prices["SPY"].index[mar]
    # Feb 2, 12-1 momentum = close[t-1]/close[t-3] - 1: AAA 1.03^2, BBB 1.02^2, CCC 1.01^2, ...
    # top 2 eligible -> AAA, BBB; ranks 4 (DDD) and 5 (EEE) are outside the top 3 -> exit flags
    # Mar 2: CCC (+5%/day) and BBB lead; AAA (-2%/day) is last -> exit, not bought
    assert entries == {"AAA": [d_feb], "BBB": [d_feb, d_mar], "CCC": [d_mar], "DDD": [], "EEE": []}
    assert exits["AAA"] == [d_mar]
    # Mar 2 ranks: CCC 1, BBB 2, DDD 3, EEE 4, AAA 5 -> DDD stays (top 3), EEE and AAA exit
    assert exits["DDD"] == [d_feb]
    assert exits["EEE"] == [d_feb, d_mar]
    assert exits["BBB"] == [] and exits["CCC"] == []
    assert out["CCC"]["score"].loc[d_mar] > out["BBB"]["score"].loc[d_mar]
    assert "locul 1" in out["CCC"]["entry_reason"].loc[d_mar]


def test_s2_no_new_entries_when_spy_below_sma():
    prices, _, _ = _s2_universe(spy_step=-1.0)
    out = s2.signals(prices, S2_SMALL)
    assert not any(f["entry"].any() for f in out.values())
    assert out["DDD"]["exit"].any()  # exits still happen at the rebalance


# --- S3 RSI-2 Pullback ---------------------------------------------------------------

S3_SMALL = s3.Params(
    sma_filter=20,
    rsi_period=2,
    rsi_entry=10,
    exit_sma=5,
    max_hold_bars=10,
    atr_period=2,
    stop_atr=3.0,
)
# ramp +1 per bar to 124 (bar 24), two drops of 3.5, then a rebound
S3_CLOSES = [100 + i for i in range(25)] + [120.5, 117, 119, 123]


def test_s3_pullback_entry_and_exit():
    prices = {"AAA": from_closes(S3_CLOSES), "SPY": spy_trend(len(S3_CLOSES), 1.0)}
    out = s3.signals(prices, S3_SMALL)["AAA"]
    # RSI2: gains 1 then losses 3.5, 3.5 -> bar 25: gain 0.5, loss 1.75 -> 22.2
    #       bar 26: gain 0.25, loss 2.625 -> RS 0.0952 -> RSI 8.70 < 10
    # SMA20 on bar 26 = (107+...+124 + 120.5 + 117)/20 = 115.825 < Close 117
    assert out.index[out["entry"]].tolist() == [out.index[26]]
    # exit: bar 27 Close 119 < SMA5 120.7; bar 28 Close 123 > SMA5 120.7
    assert not out["exit"].iloc[27]
    assert out["exit"].iloc[28]
    assert "RSI(2) 8.7 < 10" in out["entry_reason"].iloc[26]
    assert out["score"].iloc[26] == pytest.approx(-(100 - 100 / (1 + 0.25 / 2.625)))


def test_s3_time_exit_comes_from_params():
    assert load_strategy("S3").max_hold_bars == 10
    assert load_strategy("S1").max_hold_bars is None


# --- S4 MACD + EMA200 ----------------------------------------------------------------

S4_SMALL = s4.Params(
    ema_filter=3,
    macd_fast=2,
    macd_slow=3,
    macd_signal=2,
    swing_lookback=3,
    atr_period=2,
    min_stop_atr=1.5,
    target_r=1.5,
)
# steady fall of 1 per bar, then a jump to 15.5 on bar 7
S4_CLOSES = [20, 19, 18, 17, 16, 15, 14, 15.5, 15]


def test_s4_macd_cross_below_zero():
    out = s4.signals({"AAA": from_closes(S4_CLOSES)}, S4_SMALL)["AAA"]
    # steady fall: EMA2 = P + 0.5, EMA3 = P + 1 -> MACD = signal = -0.5
    # bar 7: EMA2 15.1667, EMA3 15.25 -> MACD -1/12; signal = 2/3*(-1/12) + 1/3*(-1/2) = -2/9
    # MACD crosses above the signal, both < 0, Close 15.5 > EMA3 15.25
    assert out.index[out["entry"]].tolist() == [out.index[7]]
    # 3-day low = 13.5 -> Close - low = 2.0; ATR2 = 1.74609375 -> 1.5*ATR = 2.619 (wider, wins)
    assert out["stop_distance"].iloc[7] == pytest.approx(1.5 * 1.74609375)
    assert out["target_distance"].iloc[7] == pytest.approx(1.5 * 1.5 * 1.74609375)
    assert not out["exit"].any()  # exits only at the stop or the target
    assert "ambele sub zero" in out["entry_reason"].iloc[7]


def test_s4_swing_low_stop_when_wider_than_atr_minimum():
    params = S4_SMALL.model_copy(update={"min_stop_atr": 0.5})
    out = s4.signals({"AAA": from_closes(S4_CLOSES)}, params)["AAA"]
    assert out["stop_distance"].iloc[7] == pytest.approx(2.0)  # 15.5 - 13.5
    assert out["target_distance"].iloc[7] == pytest.approx(3.0)


def test_s4_no_entry_below_ema():
    # same pattern but the jump only reaches 14.5: Close below EMA3, no entry
    closes = S4_CLOSES[:7] + [14.5, 14.0]
    out = s4.signals({"AAA": from_closes(closes)}, S4_SMALL)["AAA"]
    assert not out["entry"].any()


# --- Registry, parameters, look-ahead -------------------------------------------------


def test_yaml_params_match_the_plan():
    p = load_params()
    assert p["S1"] == {
        "sma_filter": 200,
        "entry_lookback": 55,
        "exit_lookback": 20,
        "atr_period": 20,
        "stop_atr": 2.5,
    }
    assert p["S2"]["momentum_lookback"] == 252 and p["S2"]["momentum_skip"] == 21
    assert (p["S2"]["top_n"], p["S2"]["exit_rank"], p["S2"]["stop_atr"]) == (5, 10, 3.0)
    assert (p["S3"]["rsi_period"], p["S3"]["rsi_entry"], p["S3"]["exit_sma"]) == (2, 10, 5)
    assert (p["S3"]["max_hold_bars"], p["S3"]["stop_atr"]) == (10, 3.0)
    assert (p["S4"]["macd_fast"], p["S4"]["macd_slow"], p["S4"]["macd_signal"]) == (12, 26, 9)
    assert (p["S4"]["ema_filter"], p["S4"]["swing_lookback"]) == (200, 10)
    assert (p["S4"]["min_stop_atr"], p["S4"]["target_r"]) == (1.5, 1.5)
    assert set(p) == set(MODULES)


def test_load_strategy_overrides_and_validation():
    spec = load_strategy("S1", overrides={"entry_lookback": 66})
    assert spec.params.entry_lookback == 66 and spec.params.exit_lookback == 20
    with pytest.raises(ValidationError):
        load_strategy("S1", overrides={"entry_lookbak": 66})  # typo is refused
    with pytest.raises(KeyError):
        load_strategy("S9")


UNIVERSE = {f"S{i:02d}": random_walk(650, seed=10 + i) for i in range(6)}
UNIVERSE["SPY"] = random_walk(650, seed=99, drift=0.0004, vol=0.01)


@pytest.mark.parametrize("name", sorted(MODULES))
def test_strategies_do_not_look_ahead(name):
    assert_no_lookahead(load_strategy(name).signals, UNIVERSE, n_checks=6, min_history=300)


@pytest.mark.parametrize("name", sorted(MODULES))
def test_strategies_run_in_the_backtester(name):
    spec = load_strategy(name)
    config = BacktestConfig(initial_capital=10_000.0, max_hold_bars=spec.max_hold_bars)
    sectors = {s: ("Tech" if i % 2 else "Health") for i, s in enumerate(UNIVERSE)}
    result = backtest_strategy(spec.signals, UNIVERSE, config, sectors, check_lookahead=False)
    assert "SPY" not in set(result.trades["symbol"])
    assert result.equity.iloc[-1] - 10_000.0 == pytest.approx(result.trades["pnl"].sum())
    if len(result.trades):
        assert (result.trades["entry_reason"].str.startswith(spec.title)).all()
