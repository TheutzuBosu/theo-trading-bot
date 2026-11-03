"""Tests for the sizing stub (same rules as the future risk guard)."""

import pytest

from src.backtest import sizing
from src.backtest.sizing import portfolio_rejection, size_position


def test_risk_based_size():
    # 10000 * 0.5% = 50$ risk / (100 - 90) = 5 shares
    assert size_position(100.0, 90.0, 10_000.0, 0.005) == pytest.approx(5.0)


def test_notional_cap_20_percent():
    # risk wants 50 shares, 20% of 10000 / 100 = 20 shares
    assert size_position(100.0, 99.0, 10_000.0, 0.005) == pytest.approx(20.0)


def test_config_risk_cannot_exceed_hard_max():
    # 5% asked, capped at 1%: 100$ / 10 = 10 shares
    assert size_position(100.0, 90.0, 10_000.0, 0.05) == pytest.approx(10.0)


@pytest.mark.parametrize(
    "entry, stop, equity",
    [(100.0, 100.0, 10_000.0), (100.0, 101.0, 10_000.0), (100.0, 90.0, 0.0), (0.0, -1.0, 1.0)],
)
def test_invalid_inputs_give_zero(entry, stop, equity):
    assert size_position(entry, stop, equity, 0.005) == 0.0


def test_portfolio_limits():
    assert portfolio_rejection(4, 1) is None
    assert portfolio_rejection(5, 0) == "max_positions"
    assert portfolio_rejection(3, 2) == "max_sector"


def test_stub_constants_match_plan():
    assert sizing.MAX_RISK_PER_TRADE == 0.01
    assert sizing.DEFAULT_RISK_PER_TRADE == 0.005
    assert sizing.MAX_POSITION_NOTIONAL == 0.20
    assert sizing.MAX_OPEN_POSITIONS == 5
    assert sizing.MAX_PER_SECTOR == 2
