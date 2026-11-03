"""Tests for sample state fixtures in tests/fixtures/state/ (Faza B, B6a)."""

import json
from pathlib import Path

import pandas as pd

from src.backtest.intraday_engine import TRADE_COLUMNS

STATE_DIR = Path(__file__).parent / "fixtures" / "state"


def test_sample_trades_columns_match_intraday_engine():
    df = pd.read_csv(STATE_DIR / "trades.csv")
    assert list(df.columns) == TRADE_COLUMNS
    assert len(df) >= 3
    assert df["entry_reason"].notna().all()
    assert df["exit_reason"].isin(["eod", "stop", "target"]).all()


def test_sample_equity_and_summary():
    eq = pd.read_csv(STATE_DIR / "equity.csv")
    assert list(eq.columns) == ["date", "bot_equity", "spy_buy_hold", "daily_pnl", "drawdown_pct"]
    assert eq["bot_equity"].iloc[0] == 500.0
    assert eq["spy_buy_hold"].iloc[0] == 500.0

    summary = json.loads((STATE_DIR / "summary.json").read_text(encoding="utf-8"))
    assert summary["mode"] == "PAPER"
    assert summary["is_sample"] is True
    assert summary["initial_capital"] == 500.0
    assert len(summary["positions"]) >= 1
