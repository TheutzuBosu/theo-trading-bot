"""Offline unit tests for the 13 hard-coded rules in `src/risk/guard.py` (Faza B, B5, D31)."""

from __future__ import annotations

import pandas as pd

from src.risk.guard import can_move_stop, evaluate_order_risk, symbol_family


def _valid_kwargs() -> dict:
    return {
        "symbol": "SPY",
        "direction": "long",
        "entry_price": 580.0,
        "stop": 578.0,
        "qty": 0.5,
        "equity": 500.0,
        "daily_pnl_pct": 0.0,
        "drawdown_pct": 0.0,
        "kill_switch_active": False,
        "open_positions": (),
        "current_exposure": 0.0,
        "minutes_to_close": 120.0,
        "current_spread": 0.01,
        "typical_spread": 0.01,
        "timestamp": pd.Timestamp("2026-11-04 10:30:00", tz="America/New_York"),
    }


def test_valid_order_passes_all_13_checks():
    ok, reason = evaluate_order_risk(**_valid_kwargs())
    assert ok is True
    assert reason == "OK"


def test_each_of_the_13_risk_rules_blocks_individually():
    # a. Kill switch
    ok, msg = evaluate_order_risk(**{**_valid_kwargs(), "kill_switch_active": True})
    assert not ok and "KILL switch" in msg

    # b. Max drawdown (-15%)
    ok, msg = evaluate_order_risk(**{**_valid_kwargs(), "drawdown_pct": -0.151})
    assert not ok and "Drawdown" in msg

    # c. Daily loss limit (-2%)
    ok, msg = evaluate_order_risk(**{**_valid_kwargs(), "daily_pnl_pct": -0.021})
    assert not ok and "-2%" in msg

    # d. Disallowed symbol
    ok, msg = evaluate_order_risk(**{**_valid_kwargs(), "symbol": "BTCUSD"})
    assert not ok and "Simbol nepermis" in msg

    # e. Invalid direction
    ok, msg = evaluate_order_risk(**{**_valid_kwargs(), "direction": "sideways"})
    assert not ok and "Direcție" in msg

    # f. Missing or wrong-side stop
    ok, _ = evaluate_order_risk(**{**_valid_kwargs(), "stop": None})
    assert not ok
    ok, _ = evaluate_order_risk(**{**_valid_kwargs(), "stop": 581.0})
    assert not ok
    ok, _ = evaluate_order_risk(**{**_valid_kwargs(), "direction": "short", "stop": 579.0})
    assert not ok

    # g. FOMC blackout (2025-01-29 14:10 ET is inside +/-30m of 14:00 FOMC)
    ok, msg = evaluate_order_risk(
        **{
            **_valid_kwargs(),
            "timestamp": pd.Timestamp("2025-01-29 14:10:00", tz="America/New_York"),
        }
    )
    assert not ok and "FOMC" in msg

    # h. Last 15 minutes of session
    ok, msg = evaluate_order_risk(**{**_valid_kwargs(), "minutes_to_close": 14.0})
    assert not ok and "15 minute" in msg

    # i. Spread > 2x typical
    ok, msg = evaluate_order_risk(
        **{**_valid_kwargs(), "current_spread": 0.03, "typical_spread": 0.01}
    )
    assert not ok and "Spread" in msg

    # j. Position already open on the same symbol or inverse/leveraged family (D31)
    assert symbol_family("SH") == "SPY"
    assert symbol_family("QID") == "QQQ"
    ok, msg = evaluate_order_risk(**{**_valid_kwargs(), "open_positions": ("SH",)})
    assert not ok and "familia SPY" in msg

    # k. Exposure > 2x equity
    ok, msg = evaluate_order_risk(
        **{**_valid_kwargs(), "current_exposure": 800.0, "qty": 0.5, "entry_price": 580.0}
    )
    assert not ok and "Expunerea" in msg

    # l. Risk > 0.5% of equity (0.5% of 500 $ = 2.50 $; here qty=2.0 * 2.0 $ = 4.00 $)
    ok, msg = evaluate_order_risk(
        **{**_valid_kwargs(), "qty": 2.0, "entry_price": 100.0, "stop": 98.0}
    )
    assert not ok and "0,5%" in msg

    # m. Initial risk per share < 2x round-trip cost (round-trip stock = 0.03 $, 2x = 0.06 $)
    ok, msg = evaluate_order_risk(**{**_valid_kwargs(), "entry_price": 580.0, "stop": 579.96})
    assert not ok and "2x costul" in msg


def test_can_move_stop_only_tightens():
    assert can_move_stop(578.0, 579.5, "long") is True
    assert can_move_stop(578.0, 578.0, "long") is False
    assert can_move_stop(578.0, 577.0, "long") is False

    assert can_move_stop(582.0, 580.5, "short") is True
    assert can_move_stop(582.0, 583.0, "short") is False
