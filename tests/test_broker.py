"""Offline unit tests for `src/broker/alpaca_paper.py` (Faza B, B5, D31)."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from src.broker.alpaca_paper import (
    AlpacaPaperAdapter,
    make_client_order_id,
    resolve_execution_instrument,
)


class FakeTradingClient:
    def __init__(self, equity: float = 500.0, shorting_enabled: bool = False) -> None:
        self.equity = equity
        self.shorting_enabled = shorting_enabled
        self.positions = [
            SimpleNamespace(
                symbol="SPY",
                qty="0.5",
                side="long",
                avg_entry_price="580.0",
                current_price="582.0",
                unrealized_pl="1.0",
            )
        ]
        self.submitted_orders: list[dict] = []
        self.canceled = False
        self.closed_all = False

    def get_account(self):
        return SimpleNamespace(
            equity=str(self.equity),
            cash=str(self.equity),
            buying_power=str(self.equity),
            shorting_enabled=self.shorting_enabled,
            multiplier="1",
        )

    def get_all_positions(self):
        return list(self.positions)

    def submit_order(self, order_payload: dict):
        self.submitted_orders.append(order_payload)
        return SimpleNamespace(id=f"ord-{len(self.submitted_orders)}")

    def cancel_orders(self):
        self.canceled = True

    def close_all_positions(self, cancel_orders: bool = True):
        self.closed_all = True
        self.positions.clear()


def test_live_mode_blocked_without_approval_and_gate2_pass(tmp_path: Path):
    client = FakeTradingClient()
    with pytest.raises(RuntimeError, match="TRADING_MODE=LIVE este interzis"):
        AlpacaPaperAdapter(client, trading_mode="LIVE", root_dir=tmp_path)

    # Create LIVE_APPROVED.md alone -> still blocked without gate2.md PASS
    (tmp_path / "LIVE_APPROVED.md").write_text("Approved\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="TRADING_MODE=LIVE este interzis"):
        AlpacaPaperAdapter(client, trading_mode="LIVE", root_dir=tmp_path)

    # Create gate2.md with PASS -> allowed
    (tmp_path / "reports").mkdir()
    (tmp_path / "reports" / "gate2.md").write_text("Verdict: PASS\n", encoding="utf-8")
    adapter = AlpacaPaperAdapter(client, trading_mode="LIVE", root_dir=tmp_path)
    assert adapter.trading_mode == "LIVE"


def test_d31_short_and_leverage_mapping_on_500_dollar_account():
    # Short SPY on 500 $ account (shorting_enabled=False) -> buys SH (1x) or SDS (2x)
    res_1x = resolve_execution_instrument(
        symbol="SPY",
        direction="short",
        qty=0.4,
        entry_price=580.0,
        stop_price=582.9,  # +0.5% adverse move on SPY
        target_price=574.2,  # -1.0% favorable move on SPY
        leverage=1,
        account_equity=500.0,
        shorting_enabled=False,
        instrument_price=45.0,
    )
    assert res_1x["exec_symbol"] == "SH"
    assert res_1x["side"] == "buy"
    assert res_1x["via_inverse_etf"] is True
    assert res_1x["stop_price"] < 45.0
    assert res_1x["target_price"] > 45.0

    # Short QQQ with 2x leverage on 500 $ account -> buys QID
    res_2x = resolve_execution_instrument(
        symbol="QQQ",
        direction="short",
        qty=0.4,
        entry_price=500.0,
        stop_price=502.5,
        leverage=2,
        account_equity=500.0,
        shorting_enabled=False,
        instrument_price=30.0,
    )
    assert res_2x["exec_symbol"] == "QID"
    assert res_2x["side"] == "buy"
    assert res_2x["stop_price"] < 30.0

    # Long SPY with 2x leverage -> buys SSO
    res_long_2x = resolve_execution_instrument(
        symbol="SPY",
        direction="long",
        qty=0.4,
        entry_price=580.0,
        stop_price=577.1,
        leverage=2,
        account_equity=500.0,
        shorting_enabled=False,
        instrument_price=80.0,
    )
    assert res_long_2x["exec_symbol"] == "SSO"
    assert res_long_2x["side"] == "buy"


def test_idempotency_stop_requirement_reconcile_and_liquidate_all():
    client = FakeTradingClient(equity=500.0, shorting_enabled=False)
    adapter = AlpacaPaperAdapter(client, trading_mode="PAPER")

    # Stop required
    cid = make_client_order_id("SPY", "2026-11-04T10:12:00-05:00", "long")
    with pytest.raises(ValueError, match="stop_price"):
        adapter.submit_long_with_stop("SPY", 0.5, 0.0, cid, entry_price=580.0)

    # First submission succeeds
    ord1 = adapter.submit_long_with_stop("SPY", 0.5, 578.0, cid, entry_price=580.0)
    assert ord1["status"] == "submitted"
    assert len(client.submitted_orders) == 1

    # Duplicate submission with same client_order_id is skipped idempotently
    ord2 = adapter.submit_long_with_stop("SPY", 0.5, 578.0, cid, entry_price=580.0)
    assert ord2["status"] == "duplicate_skipped"
    assert len(client.submitted_orders) == 1

    # Short submission on 500 $ account routes to PSQ
    cid_short = make_client_order_id("QQQ", "2026-11-04T10:58:00-05:00", "short")
    ord_short = adapter.submit_order_with_stop(
        symbol="QQQ",
        direction="short",
        qty=0.4,
        entry_price=500.0,
        stop_price=502.0,
        client_order_id=cid_short,
        instrument_price=40.0,
    )
    assert ord_short["symbol"] == "PSQ"
    assert ord_short["side"] == "buy"
    assert ord_short["via_inverse_etf"] is True

    # Reconcile
    rec = adapter.reconcile({"SPY", "QQQ"})
    assert rec["in_sync"] is False
    assert rec["missing_at_broker"] == ["QQQ"]

    # Liquidate all
    closed_count = adapter.liquidate_all()
    assert closed_count == 1
    assert client.canceled is True
    assert client.closed_all is True
