"""Engine tests on hand-built scenarios (expected values computed by hand in the comments)."""

import numpy as np
import pytest

from src.backtest.engine import BacktestConfig, CostModel, run_backtest
from tests.bt_helpers import bars, panels, signal_frame

CAP = BacktestConfig(initial_capital=10_000.0)
BUY = 1.0015  # 1 + slippage 0.10% + half spread 0.05%
SELL = 0.9985


def _run(rows, entries=(), exits=(), config=CAP, **signal_kw):
    prices = bars(rows)
    sig = signal_frame(prices.index, entries, exits, **signal_kw)
    panel, signals = panels({"AAA": prices}, {"AAA": sig})
    return run_backtest(panel, signals, config, {"AAA": "Tech"})


ROWS = [
    (100.0, 101.0, 99.0, 100.0),  # 0: entry signal at the close
    (100.0, 105.0, 98.0, 104.0),  # 1: buy at the Open
    (104.0, 108.0, 103.0, 107.0),  # 2: exit signal at the close
    (110.0, 111.0, 109.0, 110.0),  # 3: sell at the Open
    (110.0, 110.0, 109.0, 109.0),  # 4
]


def test_costs_on_a_hand_computed_trade():
    result = _run(ROWS, entries=[0], exits=[2], stop=10.0)
    trade = result.trades.iloc[0]
    # buy fill 100 * 1.0015 = 100.15; stop 100.15 - 10 = 90.15
    # qty = min(10000*0.5%/10 = 5, 10000*20%/100.15 = 19.97) = 5
    # sell fill 110 * 0.9985 = 109.835; pnl = 5 * (109.835 - 100.15) = 48.425
    # costs = 5*0.15 + 5*0.165 = 1.575 = gross 50 - net 48.425
    assert trade["entry_price"] == pytest.approx(100.15)
    assert trade["stop"] == pytest.approx(90.15)
    assert trade["qty"] == pytest.approx(5.0)
    assert trade["exit_price"] == pytest.approx(109.835)
    assert trade["pnl"] == pytest.approx(48.425)
    assert trade["r_multiple"] == pytest.approx(0.9685)
    assert trade["exit_reason"] == "signal"
    # MAE: lowest price 98 -> (98-100.15)/10; MFE: highest 110 (exit Open) -> (110-100.15)/10
    assert trade["mae_r"] == pytest.approx(-0.215)
    assert trade["mfe_r"] == pytest.approx(0.985)
    # equity after the buy: cash 10000 - 500.75 + 5 * close 104 = 10019.25
    assert result.equity.iloc[1] == pytest.approx(10_019.25)
    assert result.equity.iloc[-1] == pytest.approx(10_048.425)


def test_commission_per_order_is_charged_on_both_sides():
    config = BacktestConfig(initial_capital=10_000.0, costs=CostModel(commission=1.0))
    trade = _run(ROWS, entries=[0], exits=[2], config=config).trades.iloc[0]
    assert trade["pnl"] == pytest.approx(48.425 - 2.0)


def test_costs_are_configurable():
    no_costs = CostModel(slippage=0.0, half_spread=0.0)
    config = BacktestConfig(initial_capital=10_000.0, costs=no_costs)
    trade = _run(ROWS, entries=[0], exits=[2], config=config).trades.iloc[0]
    assert trade["pnl"] == pytest.approx(5 * (110 - 100))


def test_entry_executes_at_next_open_not_at_signal_close():
    rows = [(99.0, 101.0, 98.0, 100.0), (102.0, 103.0, 101.0, 102.5), (102.5, 103.0, 102.0, 103.0)]
    result = _run(rows, entries=[0], stop=5.0)
    trade = result.trades.iloc[0]
    assert trade["entry_date"] == result.equity.index[1]
    assert trade["entry_price"] == pytest.approx(102.0 * BUY)  # Open of bar 1, not Close 100


def test_signal_on_last_bar_is_never_executed():
    result = _run(ROWS, entries=[4])
    assert result.trades.empty
    assert result.equity.iloc[-1] == pytest.approx(10_000.0)


def test_worst_case_stop_and_target_in_same_bar():
    rows = [
        (100.0, 101.0, 99.0, 100.0),
        (100.0, 101.0, 99.0, 100.0),  # buy 100.15, stop 95.15, target 105.15
        (100.0, 106.0, 95.0, 104.0),  # touches both -> stop
        (104.0, 105.0, 103.0, 104.0),
    ]
    trade = _run(rows, entries=[0], stop=5.0, target=5.0).trades.iloc[0]
    assert trade["exit_reason"] == "stop"
    assert trade["exit_price"] == pytest.approx(95.15 * SELL)
    assert trade["r_multiple"] == pytest.approx((95.15 * SELL - 100.15) / 5.0)


def test_target_alone_exits_at_target():
    rows = [
        (100.0, 101.0, 99.0, 100.0),
        (100.0, 101.0, 99.0, 100.0),
        (100.0, 106.0, 99.0, 104.0),  # only the target 105.15 is touched
        (104.0, 105.0, 103.0, 104.0),
    ]
    trade = _run(rows, entries=[0], stop=5.0, target=5.0).trades.iloc[0]
    assert trade["exit_reason"] == "target"
    assert trade["exit_price"] == pytest.approx(105.15 * SELL)


def test_gap_below_stop_exits_at_open():
    rows = [
        (100.0, 101.0, 99.0, 100.0),
        (100.0, 101.0, 99.0, 100.0),  # stop 95.15
        (90.0, 92.0, 88.0, 91.0),  # gap down: out at the Open 90, not at 95.15
        (91.0, 92.0, 90.0, 91.0),
    ]
    trade = _run(rows, entries=[0], stop=5.0).trades.iloc[0]
    assert trade["exit_reason"] == "stop_gap"
    assert trade["exit_price"] == pytest.approx(90.0 * SELL)
    assert trade["r_multiple"] == pytest.approx((90.0 * SELL - 100.15) / 5.0)


def test_stop_can_hit_on_the_entry_bar():
    rows = [(100.0, 101.0, 99.0, 100.0), (100.0, 100.5, 94.0, 95.0), (95.0, 96.0, 94.0, 95.0)]
    trade = _run(rows, entries=[0], stop=5.0).trades.iloc[0]
    assert trade["exit_reason"] == "stop"
    assert trade["entry_date"] == trade["exit_date"]


def test_time_exit_after_max_hold_bars():
    config = BacktestConfig(initial_capital=10_000.0, max_hold_bars=2)
    trade = _run(ROWS, entries=[0], config=config).trades.iloc[0]
    # held at the close of bars 1 and 2 -> sold at the Open of bar 3
    assert trade["exit_reason"] == "time"
    assert trade["exit_price"] == pytest.approx(110.0 * SELL)
    assert trade["bars_held"] == 2


def test_open_position_is_closed_at_the_end():
    trade = _run(ROWS, entries=[0]).trades.iloc[0]
    assert trade["exit_reason"] == "end"
    assert trade["exit_price"] == pytest.approx(109.0 * SELL)


def test_delisted_symbol_is_closed_at_its_last_close():
    a = bars(ROWS)
    b = bars(ROWS[:3])  # data stops after bar 2
    panel, signals = panels(
        {"AAA": a, "BBB": b},
        {"AAA": signal_frame(a.index), "BBB": signal_frame(b.index, entries=[0])},
    )
    trade = run_backtest(panel, signals, CAP).trades.iloc[0]
    assert trade["symbol"] == "BBB"
    assert trade["exit_reason"] == "delisted"
    assert trade["exit_price"] == pytest.approx(107.0 * SELL)


def test_portfolio_limits_and_ranking():
    symbols = ["T1", "T2", "T3", "H1", "H2", "F1", "F2"]
    sectors = {"T1": "Tech", "T2": "Tech", "T3": "Tech", "H1": "Health", "H2": "Health"}
    sectors |= {"F1": "Fin", "F2": "Fin"}
    prices = {s: bars(ROWS) for s in symbols}
    scores = {"T1": 7, "T2": 6, "T3": 5, "H1": 4, "H2": 3, "F1": 2, "F2": 1}
    signals = {s: signal_frame(prices[s].index, entries=[0], score=scores[s]) for s in symbols}
    panel, sig = panels(prices, signals)
    result = run_backtest(panel, sig, CAP, sectors)
    held = set(result.trades["symbol"])
    # T3 rejected by the sector limit (2 Tech), F2 by the 5-position limit
    assert held == {"T1", "T2", "H1", "H2", "F1"}
    reasons = dict(zip(result.rejections["symbol"], result.rejections["reason"]))
    assert reasons == {"T3": "max_sector", "F2": "max_positions"}
    assert result.exposure.max() <= 1.0 + 1e-9  # no leverage


def test_cash_limits_quantity_no_leverage():
    # tiny stop -> risk sizing wants a huge position; capped at 20% of equity
    trade = _run(ROWS, entries=[0], stop=0.01).trades.iloc[0]
    assert trade["qty"] * trade["entry_price"] == pytest.approx(2_000.0)


def test_whole_shares_floor_and_skip_below_one_share():
    config = BacktestConfig(initial_capital=500.0, whole_shares=True)
    # risk 2.5$ / stop 10 -> 0.25 shares -> 0 whole shares -> skipped
    result = _run(ROWS, entries=[0], config=config, stop=10.0)
    assert result.trades.empty
    assert result.rejections["reason"].tolist() == ["qty_too_small"]
    config = BacktestConfig(initial_capital=10_000.0, whole_shares=True)
    trade = _run(ROWS, entries=[0], config=config, stop=3.0).trades.iloc[0]
    assert trade["qty"] == 16.0  # 50/3 = 16.67 -> 16


def test_already_held_symbol_is_not_bought_twice():
    result = _run(ROWS, entries=[0, 1])
    assert len(result.trades) == 1
    assert result.rejections["reason"].tolist() == ["already_held"]


def test_entry_reason_is_copied_to_trade():
    prices = bars(ROWS)
    sig = signal_frame(prices.index, entries=[0], exits=[2])
    sig["entry_reason"] = np.where(sig["entry"], "Close > max 55 zile", "")
    panel, signals = panels({"AAA": prices}, {"AAA": sig})
    trade = run_backtest(panel, signals, CAP).trades.iloc[0]
    assert trade["entry_reason"] == "Close > max 55 zile"


def test_equity_change_equals_sum_of_trade_pnl():
    from src import indicators as ind
    from tests.bt_helpers import random_walk

    prices = {s: random_walk(800, seed=i) for i, s in enumerate(["AAA", "BBB", "CCC"])}
    signals = {
        s: signal_frame(df.index)
        .assign(entry=df["close"] > ind.donchian_high(df["high"], 20))
        .assign(exit=df["close"] < ind.donchian_low(df["low"], 10))
        .assign(stop_distance=2.5 * ind.atr(df, 20))
        for s, df in prices.items()
    }
    panel, sig = panels(prices, signals)
    result = run_backtest(panel, sig, CAP, {"AAA": "Tech", "BBB": "Tech", "CCC": "Health"})
    assert len(result.trades) > 10
    assert result.equity.iloc[-1] - CAP.initial_capital == pytest.approx(result.trades["pnl"].sum())
    t = result.trades
    assert (t["mfe_r"] >= t["mae_r"]).all() and (t["mae_r"] <= 0).all()
    # a stop exit loses a bit more than 1R: the stop fill pays the selling costs
    stops = t[t["exit_reason"] == "stop"]
    assert len(stops) > 0
    risk = stops["entry_price"] - stops["stop"]
    expected = (stops["stop"] * SELL - stops["entry_price"]) / risk
    assert np.allclose(stops["r_multiple"], expected)
    assert (stops["r_multiple"] < -1.0).all()
