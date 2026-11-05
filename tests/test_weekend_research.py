from __future__ import annotations

from pathlib import Path

import pandas as pd

from src.ai.weekend_research import (
    build_weekend_briefing,
    format_weekend_telegram_message,
    summarize_weekly_performance,
)
from src.state.store import StateStore


def test_summarize_weekly_performance(tmp_path: Path) -> None:
    store = StateStore(tmp_path)
    trades = pd.DataFrame(
        [
            {
                "symbol": "LYEL",
                "direction": "long",
                "pnl": 2.17,
                "entry_reason": "Setup bun | Lecție: Tine poziția când trendul e puternic.",
            },
            {
                "symbol": "SSO",
                "direction": "long",
                "pnl": -0.93,
                "entry_reason": "Stop atins | Lecție: Asigură profitul parțial.",
            },
        ]
    )
    store.write_trades(trades)

    summary = summarize_weekly_performance(tmp_path)
    assert summary["total_trades"] == 2
    assert summary["winning_trades"] == 1
    assert summary["losing_trades"] == 1
    assert summary["win_rate_pct"] == 50.0
    assert summary["total_pnl"] == 1.24
    assert "LYEL" in summary["best_trade"]
    assert "SSO" in summary["worst_trade"]
    assert len(summary["lessons"]) >= 1


def test_build_weekend_briefing_fallback(tmp_path: Path) -> None:
    store = StateStore(tmp_path)
    store.write_trades(pd.DataFrame())

    briefing = build_weekend_briefing(state_dir=tmp_path, gemini_client=None)
    assert "period" in briefing
    assert "executive_summary_ro" in briefing
    assert "weekly_performance" in briefing
    assert "macro_outlook_ro" in briefing
    assert "tactical_plan_ro" in briefing
    assert len(briefing["key_events"]) > 0
    assert len(briefing["watchlist"]) > 0


def test_format_weekend_telegram_message() -> None:
    briefing = {
        "period": "4 - 8 Noiembrie 2026",
        "executive_summary_ro": "Săptămână de test.",
        "weekly_performance": {
            "total_trades": 5,
            "win_rate_pct": 60.0,
            "total_pnl": 4.5,
            "best_trade": "AAPL (+5.00 $)",
            "worst_trade": "TSLA (-0.50 $)",
        },
        "lessons_learned": ["Lecția 1: Protejează capitalul."],
        "macro_outlook_ro": "Outlook stabil.",
        "key_events": [{"day": "Luni", "event": "Deschidere bursă", "impact": "HIGH"}],
        "tactical_plan_ro": "Plan tactic: risc 0.5%.",
        "watchlist": [{"symbol": "SPY", "direction": "long", "thesis_ro": "Trend ascendent."}],
    }
    msg = format_weekend_telegram_message(briefing)
    assert "Raport Strategic de Weekend" in msg
    assert "4 - 8 Noiembrie 2026" in msg
    assert "Lecția 1" in msg
    assert "SPY" in msg
