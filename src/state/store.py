"""Atomic state persistence in `state/` and broker position reconciliation (Faza B, B4).

Writes and reads the exact files expected by the Next.js dashboard (`dashboard/src/lib/state.ts`)
and the live runner:
- `summary.json`
- `equity.csv`
- `trades.csv`
- `positions.json`
- `kill_switch.json`
- `autopsies.jsonl`
- `learning_stats.json`
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pandas as pd

from src.backtest.intraday_engine import TRADE_COLUMNS

EQUITY_COLUMNS = ("date", "bot_equity", "spy_buy_hold", "daily_pnl", "drawdown_pct")


def atomic_write_json(path: Path | str, payload: Any) -> None:
    """Write JSON atomically via a sibling `.tmp` file and `os.replace`."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, target)


def atomic_write_csv(path: Path | str, df: pd.DataFrame) -> None:
    """Write CSV atomically via a sibling `.tmp` file and `os.replace`."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".tmp")
    df.to_csv(tmp, index=False)
    os.replace(tmp, target)


def reconcile_positions(
    local_positions: list[dict[str, Any]],
    broker_positions: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    """Reconcile local `positions.json` with live/paper broker positions.

    Broker is always the source of truth on discrepancy (Rule 8, `AGENTS.md`).
    Returns a report with `in_sync`, `missing_at_broker`, `unexpected_at_broker`,
    `qty_mismatch`, and `synced_positions`.
    """
    local_by_sym = {str(p["symbol"]).upper(): dict(p) for p in local_positions if "symbol" in p}
    broker_by_sym = {str(k).upper(): dict(v) for k, v in broker_positions.items()}

    missing_at_broker = sorted(set(local_by_sym) - set(broker_by_sym))
    unexpected_at_broker = sorted(set(broker_by_sym) - set(local_by_sym))
    qty_mismatch: list[str] = []
    synced: list[dict[str, Any]] = []

    for sym, bpos in sorted(broker_by_sym.items()):
        b_qty = float(bpos.get("qty", 0.0))
        lpos = local_by_sym.get(sym)
        if lpos is not None:
            l_qty = float(lpos.get("qty", 0.0))
            if abs(l_qty - b_qty) > 1e-6:
                qty_mismatch.append(sym)
            merged = {**lpos, **bpos, "symbol": sym, "qty": b_qty}
        else:
            merged = {
                "symbol": sym,
                "direction": str(bpos.get("direction", "long")),
                "entry_time": str(bpos.get("entry_time", "")),
                "qty": b_qty,
                "entry_price": float(bpos.get("entry_price", 0.0)),
                "current_price": float(bpos.get("current_price", bpos.get("entry_price", 0.0))),
                "stop": float(bpos.get("stop", 0.0)),
                "initial_stop": float(bpos.get("initial_stop", bpos.get("stop", 0.0))),
                "unrealized_pnl": float(bpos.get("unrealized_pnl", 0.0)),
                "unrealized_r": float(bpos.get("unrealized_r", 0.0)),
                "entry_reason": str(bpos.get("entry_reason", "Reconciliat de la broker")),
            }
        synced.append(merged)

    in_sync = not (missing_at_broker or unexpected_at_broker or qty_mismatch)
    return {
        "in_sync": in_sync,
        "missing_at_broker": missing_at_broker,
        "unexpected_at_broker": unexpected_at_broker,
        "qty_mismatch": qty_mismatch,
        "synced_positions": synced,
    }


class StateStore:
    """Read/write interface over the `state/` folder."""

    def __init__(self, state_dir: Path | str = "state") -> None:
        self.state_dir = Path(state_dir)
        self.state_dir.mkdir(parents=True, exist_ok=True)

    @property
    def summary_path(self) -> Path:
        return self.state_dir / "summary.json"

    @property
    def positions_path(self) -> Path:
        return self.state_dir / "positions.json"

    @property
    def equity_path(self) -> Path:
        return self.state_dir / "equity.csv"

    @property
    def trades_path(self) -> Path:
        return self.state_dir / "trades.csv"

    @property
    def kill_switch_path(self) -> Path:
        return self.state_dir / "kill_switch.json"

    @property
    def autopsies_path(self) -> Path:
        return self.state_dir / "autopsies.jsonl"

    @property
    def learning_stats_path(self) -> Path:
        return self.state_dir / "learning_stats.json"

    def write_summary(self, summary: Mapping[str, Any]) -> None:
        payload = dict(summary)
        payload.setdefault("is_sample", False)
        atomic_write_json(self.summary_path, payload)
        if "positions" in payload and isinstance(payload["positions"], list):
            atomic_write_json(self.positions_path, payload["positions"])

    def read_summary(self) -> dict[str, Any]:
        if not self.summary_path.exists():
            return {}
        return json.loads(self.summary_path.read_text(encoding="utf-8"))

    def write_positions(self, positions: list[dict[str, Any]]) -> None:
        atomic_write_json(self.positions_path, positions)
        if self.summary_path.exists():
            summary = self.read_summary()
            summary["positions"] = positions
            atomic_write_json(self.summary_path, summary)

    def read_positions(self) -> list[dict[str, Any]]:
        if not self.positions_path.exists():
            return []
        return json.loads(self.positions_path.read_text(encoding="utf-8"))

    def write_equity(self, df: pd.DataFrame) -> None:
        out = (
            df.loc[:, list(EQUITY_COLUMNS)]
            if not df.empty
            else pd.DataFrame(columns=EQUITY_COLUMNS)
        )
        atomic_write_csv(self.equity_path, out)

    def read_equity(self) -> pd.DataFrame:
        if not self.equity_path.exists():
            return pd.DataFrame(columns=EQUITY_COLUMNS)
        return pd.read_csv(self.equity_path)

    def write_trades(self, df: pd.DataFrame) -> None:
        cols = [c for c in TRADE_COLUMNS if c in df.columns]
        extra = [c for c in df.columns if c not in cols]
        out = df.loc[:, cols + extra] if not df.empty else pd.DataFrame(columns=TRADE_COLUMNS)
        atomic_write_csv(self.trades_path, out)

    def read_trades(self) -> pd.DataFrame:
        if not self.trades_path.exists():
            return pd.DataFrame(columns=TRADE_COLUMNS)
        return pd.read_csv(self.trades_path)

    def set_kill_switch(
        self, active: bool, reason: str = "", triggered_at: str | None = None
    ) -> None:
        atomic_write_json(
            self.kill_switch_path,
            {"active": bool(active), "reason": reason, "triggered_at": triggered_at},
        )

    def read_kill_switch(self) -> dict[str, Any]:
        if not self.kill_switch_path.exists():
            return {"active": False, "reason": "", "triggered_at": None}
        return json.loads(self.kill_switch_path.read_text(encoding="utf-8"))

    def append_autopsy(self, record: Mapping[str, Any]) -> None:
        self.autopsies_path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(dict(record), ensure_ascii=False) + "\n"
        with self.autopsies_path.open("a", encoding="utf-8") as fh:
            fh.write(line)

    def read_autopsies(self) -> list[dict[str, Any]]:
        if not self.autopsies_path.exists():
            return []
        lines = self.autopsies_path.read_text(encoding="utf-8").splitlines()
        return [json.loads(line) for line in lines if line.strip()]

    def write_learning_stats(self, stats: Mapping[str, Any]) -> None:
        atomic_write_json(self.learning_stats_path, dict(stats))

    def read_learning_stats(self) -> dict[str, Any]:
        if not self.learning_stats_path.exists():
            return {}
        return json.loads(self.learning_stats_path.read_text(encoding="utf-8"))


def init_clean_paper_state(
    state_dir: Path | str = "state",
    initial_capital: float = 500.0,
    date_str: str = "2026-11-04",
    updated_at: str = "2026-11-04T09:30:00-05:00",
) -> StateStore:
    """Initialize a fresh 500.00 $ Paper state (0 trades, 0 open positions, is_sample=False)."""
    store = StateStore(state_dir)
    store.write_summary(
        {
            "mode": "PAPER",
            "is_sample": False,
            "initial_capital": float(initial_capital),
            "equity": float(initial_capital),
            "total_pnl": 0.0,
            "total_pnl_pct": 0.0,
            "today_pnl": 0.0,
            "today_pnl_pct": 0.0,
            "current_drawdown_pct": 0.0,
            "max_drawdown_pct": 0.0,
            "updated_at": updated_at,
            "positions": [],
        }
    )
    store.write_equity(
        pd.DataFrame(
            [
                {
                    "date": date_str,
                    "bot_equity": float(initial_capital),
                    "spy_buy_hold": float(initial_capital),
                    "daily_pnl": 0.0,
                    "drawdown_pct": 0.0,
                }
            ]
        )
    )
    store.write_trades(pd.DataFrame(columns=TRADE_COLUMNS))
    store.set_kill_switch(active=False, reason="", triggered_at=None)
    return store
