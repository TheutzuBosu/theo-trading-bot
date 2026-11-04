"""Offline unit tests for StateStore, broker reconciliation, autopsy, and news veto (Faza B, B4)."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from src.ai.autopsy import build_autopsy_record, classify_trade_outcome, generate_trade_lesson
from src.ai.news_veto import check_news_veto, fetch_recent_news
from src.state.store import StateStore, init_clean_paper_state, reconcile_positions


def test_init_clean_paper_state_and_store_roundtrip(tmp_path: Path):
    store = init_clean_paper_state(tmp_path / "state", initial_capital=500.0)
    summary = store.read_summary()
    assert summary["mode"] == "PAPER"
    assert summary["is_sample"] is False
    assert summary["initial_capital"] == 500.0
    assert summary["equity"] == 500.0
    assert summary["positions"] == []

    eq = store.read_equity()
    assert len(eq) == 1
    assert float(eq["bot_equity"].iloc[0]) == 500.0

    trades = store.read_trades()
    assert trades.empty

    ks = store.read_kill_switch()
    assert ks["active"] is False
    store.set_kill_switch(True, reason="Drawdown -15%", triggered_at="2026-11-04T14:00:00-05:00")
    assert store.read_kill_switch()["active"] is True


def test_reconcile_positions_prefers_broker_as_source_of_truth():
    local = [
        {"symbol": "SPY", "direction": "long", "qty": 0.5, "entry_price": 580.0, "stop": 578.0},
        {"symbol": "QQQ", "direction": "long", "qty": 0.4, "entry_price": 500.0, "stop": 498.0},
    ]
    broker = {
        "SPY": {"qty": 0.8, "entry_price": 580.0, "current_price": 582.0, "stop": 579.0},
        "SH": {"qty": 5.0, "entry_price": 45.0, "current_price": 45.5, "stop": 44.5},
    }
    report = reconcile_positions(local, broker)
    assert report["in_sync"] is False
    assert report["missing_at_broker"] == ["QQQ"]
    assert report["unexpected_at_broker"] == ["SH"]
    assert report["qty_mismatch"] == ["SPY"]
    by_sym = {p["symbol"]: p for p in report["synced_positions"]}
    assert by_sym["SPY"]["qty"] == 0.8
    assert "SH" in by_sym
    assert "QQQ" not in by_sym


def test_autopsy_classification_and_romanian_lesson(tmp_path: Path):
    win_trade = {
        "symbol": "SPY",
        "direction": "long",
        "entry_time": "2026-11-04 10:12:00-05:00",
        "exit_time": "2026-11-04 11:30:00-05:00",
        "pnl": 4.20,
        "r_multiple": 1.85,
        "mfe_r": 2.10,
        "mae_r": -0.15,
        "exit_reason": "target",
        "partial_exit": True,
        "entry_reason": "D1b long",
    }
    assert classify_trade_outcome(win_trade) == "win_target"
    rec = build_autopsy_record(win_trade, client=None)
    assert "SPY" in rec["lesson"]
    assert rec["category"] == "win_target"

    loss_reversal = {
        **win_trade,
        "pnl": -2.10,
        "r_multiple": -1.0,
        "mfe_r": 0.80,
        "exit_reason": "stop",
        "partial_exit": False,
    }
    assert classify_trade_outcome(loss_reversal) == "loss_reversal_after_gain"

    # Mock Gemini client
    fake_client = SimpleNamespace(
        models=SimpleNamespace(
            generate_content=lambda model, contents: SimpleNamespace(
                text="Lecție AI: intrarea pe SPY a atins ținta rapid."
            )
        )
    )
    assert generate_trade_lesson(win_trade, client=fake_client) == (
        "Lecție AI: intrarea pe SPY a atins ținta rapid."
    )

    store = StateStore(tmp_path / "state")
    store.append_autopsy(rec)
    autopsies = store.read_autopsies()
    assert len(autopsies) == 1
    assert autopsies[0]["symbol"] == "SPY"


def test_news_veto_crisis_block_and_gemini_json_and_fallback():
    # Empty headlines -> allow
    allow, reason = check_news_veto("SPY", "long", [])
    assert allow is True

    # Explicit circuit breaker / trading halt keyword -> block deterministically
    allow_halt, reason_halt = check_news_veto(
        "SPY", "long", ["NYSE announces market-wide circuit breaker trading halt"]
    )
    assert allow_halt is False
    assert "Veto" in reason_halt

    # Gemini JSON response blocking trade
    block_client = SimpleNamespace(
        models=SimpleNamespace(
            generate_content=lambda model, contents: SimpleNamespace(
                text='{"allow": false, "reason": "Șoc macroeconomic major în desfășurare."}'
            )
        )
    )
    allow_ai, reason_ai = check_news_veto(
        "QQQ", "long", ["Unexpected geopolitical shock hits tech sector"], client=block_client
    )
    assert allow_ai is False
    assert "Șoc" in reason_ai

    # Broken Gemini client -> fails open (allow = True)
    def _raise(model, contents):
        raise RuntimeError("timeout")

    broken_client = SimpleNamespace(models=SimpleNamespace(generate_content=_raise))
    allow_fb, _ = check_news_veto("QQQ", "long", ["Normal earnings report"], client=broken_client)
    assert allow_fb is True


def test_fetch_recent_news_with_mock_session():
    now = datetime(2026, 11, 4, 15, 0, tzinfo=timezone.utc)
    recent_ts = (now.timestamp()) - 1800

    class FakeSession:
        def get(self, url, params=None, timeout=None):
            return SimpleNamespace(
                status_code=200,
                json=lambda: [
                    {"headline": "SPY steady ahead of session", "datetime": recent_ts},
                ],
            )

    items = fetch_recent_news("SPY", finnhub_key="fake-key", session=FakeSession(), now_utc=now)
    assert len(items) == 1
    assert items[0]["headline"] == "SPY steady ahead of session"
    assert fetch_recent_news("SPY", finnhub_key="") == []
