"""Offline unit tests for `src/live/state_writer.py` and `src/live/runner.py` (Faza B, B6c)."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd

from src.broker.alpaca_paper import AlpacaPaperAdapter
from src.live.runner import (
    evaluate_mover_candidate,
    evaluate_symbol_candidate,
    initialize_live_paper_state,
    run_end_of_day_learning,
    run_kill_switch,
    run_trading_step,
)
from src.live.state_writer import (
    ensure_github_state_branch,
    push_file_to_github_branch,
    write_state_files,
)
from src.state.store import StateStore
from tests.live_fakes import FakeAlpaca, make_intraday_bars

NY = ZoneInfo("America/New_York")


class FakeResponse:
    def __init__(self, status_code: int, payload: dict[str, Any] | None = None) -> None:
        self.status_code = status_code
        self._payload = payload or {}

    def json(self) -> dict[str, Any]:
        return self._payload


class FakeGitHubSession:
    def __init__(self, branch_exists: bool = False) -> None:
        self.branch_exists = branch_exists
        self.gets: list[str] = []
        self.posts: list[tuple[str, dict[str, Any]]] = []
        self.puts: list[tuple[str, dict[str, Any]]] = []

    def get(
        self, url: str, headers: Any = None, params: Any = None, timeout: int = 10
    ) -> FakeResponse:
        self.gets.append(url)
        if url.endswith("/git/ref/heads/state"):
            if self.branch_exists:
                return FakeResponse(200, {"object": {"sha": "abc123state"}})
            return FakeResponse(404, {})
        if url.endswith("/git/ref/heads/main"):
            return FakeResponse(200, {"object": {"sha": "mainsha123"}})
        if "/contents/state/" in url:
            return FakeResponse(200, {"sha": "oldfilesha"})
        if "finnhub.io" in url:
            return FakeResponse(200, [])  # type: ignore[arg-type]
        return FakeResponse(404, {})

    def post(
        self, url: str, headers: Any = None, json: Any = None, timeout: int = 10
    ) -> FakeResponse:
        self.posts.append((url, json or {}))
        if url.endswith("/git/refs"):
            self.branch_exists = True
            return FakeResponse(201, {"ref": "refs/heads/state"})
        if "api.telegram.org" in url:
            return FakeResponse(200, {"ok": True})
        return FakeResponse(200, {"ok": True})

    def put(
        self, url: str, headers: Any = None, json: Any = None, timeout: int = 10
    ) -> FakeResponse:
        self.puts.append((url, json or {}))
        return FakeResponse(200, {"content": {"name": url.split("/")[-1]}})


NOW_CHECK = datetime(2026, 10, 22, 10, 12, 8, tzinfo=NY)  # 8 s after the 10:11 bar closed
PRICES = {"SSO": 80.0, "QID": 30.0, "SDS": 56.0, "SH": 33.0, "PSQ": 27.0, "QLD": 81.0}


def _adapter(client: FakeAlpaca, tmp_path: Path) -> AlpacaPaperAdapter:
    return AlpacaPaperAdapter(client, root_dir=tmp_path, sleep=lambda _s: None)


def test_github_state_branch_and_write_state_files(tmp_path: Path) -> None:
    session = FakeGitHubSession(branch_exists=False)
    assert ensure_github_state_branch("gh-token", session=session) is True
    assert session.branch_exists is True

    ok = push_file_to_github_branch(
        "state/summary.json",
        '{"is_sample": false}',
        "chore: init",
        token="gh-token",
        session=session,
    )
    assert ok is True
    assert len(session.puts) == 1

    summary = {"mode": "PAPER", "is_sample": True, "initial_capital": 500.0, "equity": 500.0}
    eq_df = pd.DataFrame(
        [
            {
                "date": "2026-11-04",
                "bot_equity": 500.0,
                "spy_buy_hold": 500.0,
                "daily_pnl": 0.0,
                "drawdown_pct": 0.0,
            }
        ]
    )
    tr_df = pd.DataFrame()
    sync_res = write_state_files(
        tmp_path,
        summary,
        eq_df,
        tr_df,
        sync_github=True,
        github_token="gh-token",
        session=session,
    )
    assert sync_res.get("summary.json") is True
    stored = StateStore(tmp_path).read_summary()
    assert stored["is_sample"] is False


def test_initialize_live_paper_state_resets_sample_flag(tmp_path: Path) -> None:
    client = FakeAlpaca(prices=PRICES)
    adapter = _adapter(client, tmp_path)
    session = FakeGitHubSession(branch_exists=True)

    summary = initialize_live_paper_state(
        tmp_path,
        adapter=adapter,
        initial_capital=500.0,
        as_of_date="2026-11-04",
        sync_github=True,
        github_token="gh-token",
        session=session,
    )
    assert summary["is_sample"] is False
    assert summary["equity"] == 500.0
    assert summary["initial_capital"] == 500.0
    assert summary["positions"] == []


def test_evaluate_candidate_and_run_trading_step_long_and_short(tmp_path: Path) -> None:
    bars_long = make_intraday_bars(days=16, breakout_last_day="long")
    bars_short = make_intraday_bars(days=16, breakout_last_day="short")

    cand_short = evaluate_symbol_candidate(
        "QQQ",
        bars_short,
        equity=500.0,
        open_positions=set(),
        current_exposure=0.0,
        daily_pnl_pct=0.0,
        drawdown_pct=0.0,
        leverage=2,
        shorting_enabled=False,
        etf_prices=PRICES,
        now_et=NOW_CHECK,
        http_session=FakeGitHubSession(branch_exists=True),
    )
    assert cand_short["action"] == "enter"
    assert cand_short["signal_direction"] == "short"
    assert cand_short["exec_symbol"] == "QID"  # -2x inverse ETF for QQQ on 500$ account
    # The stop is computed on QID's own price (~30 $), never on the QQQ level (~575 $)
    assert 25.0 < cand_short["stop_price"] < 30.0
    assert cand_short["entry_price"] == 30.0

    client = FakeAlpaca(prices=PRICES)
    adapter = _adapter(client, tmp_path)
    session = FakeGitHubSession(branch_exists=True)

    step = run_trading_step(
        state_dir=tmp_path,
        adapter=adapter,
        bars_by_symbol={"SPY": bars_long, "QQQ": bars_short},
        leverage=2,
        http_session=session,
        sync_github=True,
        github_token="gh-token",
        send_alerts=False,
        prices=PRICES,
        now_et=NOW_CHECK,
    )
    assert step["status"] == "ok"
    assert len(step["orders"]) == 2
    exec_syms = {o["exec_symbol"] for o in step["orders"]}
    assert exec_syms == {"SSO", "QID"}
    assert all(o["status"] == "filled" for o in step["orders"])
    # Each entry is a real market order followed by a real stop order on the filled quantity
    kinds = [type(r).__name__ for r in client.submitted]
    assert kinds == ["MarketOrderRequest", "StopOrderRequest"] * 2
    assert set(client.positions) == {"SSO", "QID"}
    journal = StateStore(tmp_path).read_journal()
    assert set(journal["open_trades"]) == {"SSO", "QID"}
    assert len(journal["processed_signals"]) == 2


def test_end_of_day_learning_and_kill_switch(tmp_path: Path) -> None:
    client = FakeAlpaca(prices=PRICES)
    adapter = _adapter(client, tmp_path)
    session = FakeGitHubSession(branch_exists=True)

    initialize_live_paper_state(tmp_path, adapter=adapter, as_of_date="2026-11-04")

    sample_trade = {
        "symbol": "SPY",
        "direction": "long",
        "signal_time": "2026-11-04 10:00:00-05:00",
        "entry_time": "2026-11-04 10:01:00-05:00",
        "entry_open": 580.0,
        "entry_price": 580.02,
        "exit_time": "2026-11-04 15:59:00-05:00",
        "exit_raw": 583.50,
        "exit_price": 583.48,
        "qty": 0.85,
        "initial_stop": 577.10,
        "stop": 581.00,
        "target": 585.00,
        "initial_risk": 2.92,
        "risk_pct": 0.005,
        "notional_pct": 0.98,
        "pnl": 2.94,
        "r_multiple": 1.18,
        "mae_r": -0.15,
        "mfe_r": 1.30,
        "bars_held": 358,
        "equity_at_entry": 500.0,
        "exit_reason": "eod",
        "exit_at_open": False,
        "partial_exit": False,
        "entry_reason": "D1b spargere banda zgomot 10:00 ET",
        "entry_bar": 31,
        "exit_bar": 389,
    }

    eod_res = run_end_of_day_learning(
        state_dir=tmp_path,
        adapter=adapter,
        closed_trades_today=[sample_trade],
        http_session=session,
        sync_github=True,
        github_token="gh-token",
        send_alerts=False,
    )
    assert eod_res["new_trades_recorded"] == 1
    assert len(eod_res["lessons"]) == 1

    store = StateStore(tmp_path)
    trades_df = store.read_trades()
    assert len(trades_df) == 1
    assert "Lecție:" in str(trades_df.iloc[0]["entry_reason"])
    assert len(store.read_autopsies()) == 1

    kill_res = run_kill_switch(
        state_dir=tmp_path,
        adapter=adapter,
        reason="Test KILL switch",
        sync_github=True,
        github_token="gh-token",
        send_alerts=False,
        http_session=session,
    )
    assert kill_res["active"] is True
    assert store.read_kill_switch()["active"] is True


def test_evaluate_mover_candidate_and_stock_opportunities_execution(tmp_path: Path) -> None:
    prices = {**PRICES, "NVDA": 140.0, "INTC": 22.0, "SOXS": 25.0}
    opp_long = {
        "symbol": "NVDA",
        "action": "enter",
        "direction": "long",
        "price": 140.0,
        "change_pct": 6.4,
        "stop_price": 137.90,
        "target_price": 150.50,
        "rr_ratio": 5.0,
        "stake_dollars": 15.0,
        "confidence": 0.82,
        "reason_ro": "NVDA crește puternic (+6.4%) pe investiții AI masive (R:R 1:5.0).",
    }
    opp_short = {
        "symbol": "INTC",
        "action": "enter",
        "direction": "short",
        "price": 22.0,
        "change_pct": -14.8,
        "stop_price": 22.33,
        "target_price": 20.02,
        "rr_ratio": 6.0,
        "stake_dollars": 10.0,
        "confidence": 0.78,
        "reason_ro": "INTC scade -14.8% în pre-market după raport financiar slab (R:R 1:6.0).",
    }

    cand_long = evaluate_mover_candidate(
        opp_long,
        equity=500.0,
        open_positions=set(),
        current_exposure=0.0,
        daily_pnl_pct=0.0,
        drawdown_pct=0.0,
        prices=prices,
        now_et=NOW_CHECK,
    )
    assert cand_long["action"] == "enter"
    assert cand_long["exec_symbol"] == "NVDA"
    assert cand_long["exec_direction"] == "long"
    assert round(cand_long["qty"] * cand_long["entry_price"], 2) <= 15.05

    cand_short = evaluate_mover_candidate(
        opp_short,
        equity=500.0,
        open_positions=set(),
        current_exposure=0.0,
        daily_pnl_pct=0.0,
        drawdown_pct=0.0,
        prices=prices,
        now_et=NOW_CHECK,
    )
    assert cand_short["action"] == "enter"
    assert cand_short["signal_symbol"] == "INTC"
    assert cand_short["exec_symbol"] == "SOXS"  # inverse semiconductor ETF on 500$ account

    client = FakeAlpaca(prices=prices)
    adapter = _adapter(client, tmp_path)
    session = FakeGitHubSession(branch_exists=True)

    step = run_trading_step(
        state_dir=tmp_path,
        adapter=adapter,
        bars_by_symbol={"SPY": pd.DataFrame(), "QQQ": pd.DataFrame()},
        http_session=session,
        sync_github=False,
        send_alerts=False,
        prices=prices,
        now_et=NOW_CHECK,
        stock_opportunities=[opp_long, opp_short],
    )
    assert step["status"] == "ok"
    assert {o["exec_symbol"] for o in step["orders"]} == {"NVDA", "SOXS"}
