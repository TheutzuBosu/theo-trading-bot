"""Offline unit tests for `src/live/state_writer.py` and `src/live/runner.py` (Faza B, B6c)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from src.broker.alpaca_paper import AlpacaPaperAdapter
from src.live.runner import (
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


class FakeAccount:
    equity = "500.00"
    cash = "500.00"
    buying_power = "500.00"
    shorting_enabled = False
    multiplier = "1"


class FakeTradingClient:
    def __init__(self) -> None:
        self.account = FakeAccount()
        self.positions: list[Any] = []
        self.submitted_orders: list[Any] = []
        self.closed_all = False

    def get_account(self) -> FakeAccount:
        return self.account

    def get_all_positions(self) -> list[Any]:
        return list(self.positions)

    def submit_order(self, order_data: Any) -> dict[str, Any]:
        self.submitted_orders.append(order_data)
        return {"id": f"ord-{len(self.submitted_orders)}"}

    def cancel_orders(self) -> list[Any]:
        return []

    def close_all_positions(self, cancel_orders: bool = True) -> list[Any]:
        n = len(self.positions)
        self.positions.clear()
        self.closed_all = True
        return [object() for _ in range(n)]


def _make_intraday_bars(days: int = 16, breakout_last_day: str = "long") -> pd.DataFrame:
    """Build synthetic 1-minute NYSE session bars across `days` sessions."""
    sessions = pd.bdate_range("2026-10-01", periods=days)
    rows: list[dict[str, float]] = []
    idx: list[pd.Timestamp] = []
    rng = np.random.default_rng(123)

    for d_i, day in enumerate(sessions):
        day_str = day.strftime("%Y-%m-%d")
        minutes = pd.date_range(
            f"{day_str} 09:30",
            f"{day_str} 15:59",
            freq="1min",
            tz="America/New_York",
        )
        base = 580.0
        for m_i, ts in enumerate(minutes):
            if d_i < days - 1:
                # Tight noise around 580.0
                noise = 0.05 * np.sin(m_i / 10.0) + float(rng.normal(0, 0.02))
                c = base + noise
                o = c - 0.01
                h = c + 0.04
                low = c - 0.04
                vwap = base
            else:
                # Last day: at 10:11 ET (m_i == 41), strong breakout
                if m_i <= 41:
                    if breakout_last_day == "long":
                        c = base + (m_i / 41.0) * 4.5
                        vwap = base + (m_i / 41.0) * 1.5
                    elif breakout_last_day == "short":
                        c = base - (m_i / 41.0) * 4.5
                        vwap = base - (m_i / 41.0) * 1.5
                    else:
                        c = base
                        vwap = base
                    o = c - 0.05
                    h = c + 0.10
                    low = c - 0.10
                else:
                    c = base
                    o = base
                    h = base + 0.05
                    low = base - 0.05
                    vwap = base
            rows.append(
                {
                    "open": o,
                    "high": h,
                    "low": low,
                    "close": c,
                    "volume": 50_000.0,
                    "trade_count": 400.0,
                    "vwap": vwap,
                }
            )
            idx.append(ts)

    df = pd.DataFrame(rows, index=pd.DatetimeIndex(idx, name="timestamp"))
    # Slice on the last day at 10:11 ET (m_i == 41, index -348) so the last bar is the D1b check bar
    return df.iloc[:-348]


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
    client = FakeTradingClient()
    adapter = AlpacaPaperAdapter(client, root_dir=tmp_path)
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
    bars_long = _make_intraday_bars(days=16, breakout_last_day="long")
    bars_short = _make_intraday_bars(days=16, breakout_last_day="short")

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
    )
    assert cand_short["action"] == "enter"
    assert cand_short["signal_direction"] == "short"
    assert cand_short["exec_symbol"] == "QID"  # -2x inverse ETF for QQQ on 500$ account

    client = FakeTradingClient()
    adapter = AlpacaPaperAdapter(client, root_dir=tmp_path)
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
    )
    assert step["status"] == "ok"
    assert len(step["orders"]) == 2
    exec_syms = {o["exec_symbol"] for o in step["orders"]}
    assert exec_syms == {"SSO", "QID"}


def test_end_of_day_learning_and_kill_switch(tmp_path: Path) -> None:
    client = FakeTradingClient()
    adapter = AlpacaPaperAdapter(client, root_dir=tmp_path)
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
