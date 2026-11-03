"""Tests for the Faza B cost model (src/backtest/intraday_costs.py)."""

import pytest

from src.backtest.intraday_costs import (
    STRESS_FACTOR,
    cost_per_side,
    fill_price,
    net_pnl_per_share,
    r_multiple,
    round_trip_cost,
    trade_allowed,
)


def test_stock_costs():
    assert cost_per_side("SPY") == pytest.approx(0.015)
    assert cost_per_side("qqq", "stock") == pytest.approx(0.015)
    assert round_trip_cost("SPY") == pytest.approx(0.03)


def test_cfd_costs_in_etf_units():
    # US500 0.8 points / 10 = 0.08 $ per SPY share; US100 2.5 / 40.8 per QQQ share
    assert cost_per_side("SPY", "cfd") == pytest.approx(0.08)
    assert cost_per_side("QQQ", "cfd") == pytest.approx(2.5 / 40.8)
    with pytest.raises(ValueError):
        cost_per_side("AAPL", "cfd")
    with pytest.raises(ValueError):
        cost_per_side("SPY", "futures")


def test_stress():
    assert cost_per_side("SPY", "cfd", STRESS_FACTOR) == pytest.approx(0.12)
    assert round_trip_cost("SPY", "stock", 1.5) == pytest.approx(0.045)
    with pytest.raises(ValueError):
        cost_per_side("SPY", stress=0.5)


def test_fill_price():
    assert fill_price(600.0, "buy", 0.015) == pytest.approx(600.015)
    assert fill_price(600.0, "sell", 0.015) == pytest.approx(599.985)
    with pytest.raises(ValueError):
        fill_price(600.0, "hold", 0.015)


def test_net_pnl_long_and_short():
    # Long 600 -> 601 with 0.08 per side: 1 - 0.16
    assert net_pnl_per_share(600.0, 601.0, "long", 0.08) == pytest.approx(0.84)
    # Short 600 -> 599: 1 - 0.16
    assert net_pnl_per_share(600.0, 599.0, "short", 0.08) == pytest.approx(0.84)
    # A flat trade loses exactly the round trip
    assert net_pnl_per_share(600.0, 600.0, "long", 0.015) == pytest.approx(-0.03)
    with pytest.raises(ValueError):
        net_pnl_per_share(600.0, 601.0, "sideways", 0.015)


def test_r_multiple():
    assert r_multiple(0.84, 0.5) == pytest.approx(1.68)
    assert r_multiple(-0.5, 0.5) == pytest.approx(-1.0)
    with pytest.raises(ValueError):
        r_multiple(1.0, 0.0)


def test_trade_allowed():
    rt = round_trip_cost("SPY", "cfd")  # 0.16
    assert trade_allowed(0.32, rt)
    assert not trade_allowed(0.31, rt)
    assert trade_allowed(0.06, round_trip_cost("SPY"))
