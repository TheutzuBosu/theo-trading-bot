"""Alpaca Paper/Live broker adapter with D31 Long+Short+Leverage mapping (Faza B, B5).

Safety & design guarantees:
1. Blocks `TRADING_MODE == "LIVE"` unless both `LIVE_APPROVED.md` exists and `reports/gate2.md`
   contains `PASS` (Rule 10, `AGENTS.md`).
2. Implements `resolve_execution_instrument` (D31): on a 500 $ account (`equity < 2000` or
   `shorting_enabled=False`), short signals on `SPY`/`QQQ` automatically route to fractional
   LONG buys on liquid inverse ETFs (`SH`/`SDS` for SPY, `PSQ`/`QID` for QQQ), and 2x long
   signals can route to `SSO`/`QLD`, preserving exact dollar risk and stop distance.
3. Deterministic `client_order_id` (`make_client_order_id`) for idempotency on restart.
4. Every entry order requires a valid stop-loss; `liquidate_all()` cancels all open orders and
   closes all positions immediately.
"""

from __future__ import annotations

import math
import re
from pathlib import Path
from typing import Any

from src.config import settings

INVERSE_ETF_MAP: dict[tuple[str, int], str] = {
    ("SPY", 1): "SH",
    ("SPY", 2): "SDS",
    ("QQQ", 1): "PSQ",
    ("QQQ", 2): "QID",
}

LEVERAGED_LONG_ETF_MAP: dict[tuple[str, int], str] = {
    ("SPY", 1): "SPY",
    ("SPY", 2): "SSO",
    ("QQQ", 1): "QQQ",
    ("QQQ", 2): "QLD",
}


def assert_live_mode_allowed(
    trading_mode: str | None = None,
    root_dir: Path | str = ".",
) -> None:
    """Raise RuntimeError if `trading_mode == 'LIVE'` without LIVE_APPROVED.md and Poarta 2 PASS."""
    mode = (trading_mode if trading_mode is not None else settings.TRADING_MODE).upper()
    if mode != "LIVE":
        return

    base = Path(root_dir)
    approved_file = base / "LIVE_APPROVED.md"
    gate2_file = base / "reports" / "gate2.md"
    if not approved_file.exists():
        raise RuntimeError(
            "TRADING_MODE=LIVE este interzis fără LIVE_APPROVED.md și Poarta 2 = PASS"
        )
    if not gate2_file.exists() or "PASS" not in gate2_file.read_text(encoding="utf-8"):
        raise RuntimeError(
            "TRADING_MODE=LIVE este interzis fără LIVE_APPROVED.md și Poarta 2 = PASS"
        )


def make_client_order_id(symbol: str, timestamp_str: str, direction: str) -> str:
    """Generate a deterministic, idempotent Alpaca client_order_id (<= 48 chars)."""
    sym = re.sub(r"[^A-Z0-9]", "", symbol.upper())
    dir_tag = "L" if str(direction).lower() == "long" else "S"
    ts_clean = re.sub(r"[^0-9]", "", str(timestamp_str))[:14]
    return f"theo-{sym}-{dir_tag}-{ts_clean}"


def resolve_execution_instrument(
    *,
    symbol: str,
    direction: str,
    qty: float,
    entry_price: float,
    stop_price: float,
    target_price: float | None = None,
    leverage: int = 1,
    account_equity: float = 500.0,
    shorting_enabled: bool = False,
    instrument_price: float | None = None,
) -> dict[str, Any]:
    """Resolve a signal on `SPY`/`QQQ` into an executable order on Alpaca (D31).

    When `direction == "short"` and the account has `< 2000 $` or `shorting_enabled=False`,
    routes to buying the inverse ETF (`SH`/`SDS` for SPY; `PSQ`/`QID` for QQQ) as a long order
    with stop below entry. Preserves the planned dollar risk and caps notional to `account_equity`.
    """
    sym = symbol.upper()
    dir_norm = direction.lower()
    lev = 2 if int(leverage) >= 2 else 1

    if entry_price <= 0 or stop_price <= 0 or qty <= 0:
        raise ValueError("entry_price, stop_price, and qty must be positive")

    raw_risk_pct = abs(entry_price - stop_price) / entry_price
    if raw_risk_pct <= 0:
        raise ValueError("stop_price must differ from entry_price")
    planned_risk_dollars = qty * abs(entry_price - stop_price)
    raw_tp_pct = (
        abs(target_price - entry_price) / entry_price
        if target_price is not None and math.isfinite(target_price) and target_price > 0
        else None
    )

    # Case 1: Short signal on an account that cannot short directly (< 2000 $ or shorting disabled)
    if dir_norm == "short" and (not shorting_enabled or account_equity < 2000.0):
        exec_sym = INVERSE_ETF_MAP.get((sym, lev), sym)
        exec_price = float(instrument_price if instrument_price is not None else entry_price)
        eff_dist_pct = min(0.20, raw_risk_pct * lev)
        exec_stop = round(exec_price * (1.0 - eff_dist_pct), 4)
        exec_target = (
            round(exec_price * (1.0 + raw_tp_pct * lev), 4) if raw_tp_pct is not None else None
        )
        per_share_risk = max(exec_price - exec_stop, 1e-4)
        exec_qty = planned_risk_dollars / per_share_risk
        max_notional = max(0.0, account_equity * 0.5)
        if exec_qty * exec_price > max_notional and exec_price > 0:
            exec_qty = max_notional / exec_price
        return {
            "signal_symbol": sym,
            "signal_direction": "short",
            "exec_symbol": exec_sym,
            "exec_direction": "long",
            "side": "buy",
            "qty": round(float(exec_qty), 6),
            "entry_price": exec_price,
            "stop_price": exec_stop,
            "target_price": exec_target,
            "leverage": lev,
            "via_inverse_etf": True,
        }

    # Case 2: Long signal (1x SPY/QQQ or 2x SSO/QLD)
    if dir_norm == "long":
        exec_sym = LEVERAGED_LONG_ETF_MAP.get((sym, lev), sym)
        exec_price = float(instrument_price if instrument_price is not None else entry_price)
        if exec_sym != sym or instrument_price is not None:
            eff_dist_pct = min(0.20, raw_risk_pct * lev)
            exec_stop = round(exec_price * (1.0 - eff_dist_pct), 4)
            exec_target = (
                round(exec_price * (1.0 + raw_tp_pct * lev), 4) if raw_tp_pct is not None else None
            )
            per_share_risk = max(exec_price - exec_stop, 1e-4)
            exec_qty = planned_risk_dollars / per_share_risk
            max_notional = max(0.0, account_equity * 0.5)
            if exec_qty * exec_price > max_notional and exec_price > 0:
                exec_qty = max_notional / exec_price
        else:
            exec_stop = round(float(stop_price), 4)
            exec_target = round(float(target_price), 4) if target_price is not None else None
            exec_qty = float(qty)

        return {
            "signal_symbol": sym,
            "signal_direction": "long",
            "exec_symbol": exec_sym,
            "exec_direction": "long",
            "side": "buy",
            "qty": round(float(exec_qty), 6),
            "entry_price": exec_price,
            "stop_price": exec_stop,
            "target_price": exec_target,
            "leverage": lev,
            "via_inverse_etf": False,
        }

    # Case 3: Direct short on margin account (>= 2000 $ and shorting_enabled=True)
    whole_qty = float(max(1, int(math.floor(qty))))
    return {
        "signal_symbol": sym,
        "signal_direction": "short",
        "exec_symbol": sym,
        "exec_direction": "short",
        "side": "sell",
        "qty": whole_qty,
        "entry_price": float(entry_price),
        "stop_price": round(float(stop_price), 4),
        "target_price": round(float(target_price), 4) if target_price is not None else None,
        "leverage": lev,
        "via_inverse_etf": False,
    }


class AlpacaPaperAdapter:
    """Safe wrapper over Alpaca TradingClient for Paper (and gated Live) execution."""

    def __init__(
        self,
        trading_client: Any,
        trading_mode: str | None = None,
        root_dir: Path | str = ".",
    ) -> None:
        assert_live_mode_allowed(trading_mode=trading_mode, root_dir=root_dir)
        self.client = trading_client
        self.trading_mode = (trading_mode or settings.TRADING_MODE).upper()
        self._submitted_ids: set[str] = set()

    def get_account_state(self) -> dict[str, Any]:
        acct = self.client.get_account()
        return {
            "equity": float(getattr(acct, "equity", 0.0)),
            "cash": float(getattr(acct, "cash", 0.0)),
            "buying_power": float(getattr(acct, "buying_power", 0.0)),
            "shorting_enabled": bool(getattr(acct, "shorting_enabled", False)),
            "multiplier": int(getattr(acct, "multiplier", 1) or 1),
        }

    def get_open_positions(self) -> dict[str, dict[str, Any]]:
        raw_positions = self.client.get_all_positions()
        out: dict[str, dict[str, Any]] = {}
        for p in raw_positions:
            sym = str(getattr(p, "symbol", "")).upper()
            qty = float(getattr(p, "qty", 0.0))
            side = str(getattr(p, "side", "long")).lower()
            direction = "short" if "short" in side or qty < 0 else "long"
            out[sym] = {
                "symbol": sym,
                "direction": direction,
                "qty": abs(qty),
                "entry_price": float(getattr(p, "avg_entry_price", 0.0)),
                "current_price": float(
                    getattr(p, "current_price", getattr(p, "avg_entry_price", 0.0))
                ),
                "unrealized_pnl": float(getattr(p, "unrealized_pl", 0.0)),
            }
        return out

    def reconcile(self, local_symbols: set[str]) -> dict[str, Any]:
        broker_pos = self.get_open_positions()
        local_norm = {s.upper() for s in local_symbols}
        broker_norm = set(broker_pos.keys())
        missing = sorted(local_norm - broker_norm)
        unexpected = sorted(broker_norm - local_norm)
        return {
            "in_sync": not (missing or unexpected),
            "missing_at_broker": missing,
            "unexpected_at_broker": unexpected,
            "broker_positions": broker_pos,
        }

    def submit_order_with_stop(
        self,
        *,
        symbol: str,
        direction: str,
        qty: float,
        entry_price: float,
        stop_price: float,
        client_order_id: str,
        target_price: float | None = None,
        leverage: int = 1,
        instrument_price: float | None = None,
    ) -> dict[str, Any]:
        """Submit an idempotent order with a mandatory stop-loss (routing via D31 if needed)."""
        if stop_price is None or not math.isfinite(stop_price) or stop_price <= 0:
            raise ValueError("Refuzat: orice ordin trebuie să aibă un stop_price > 0 valid")
        if qty <= 0:
            raise ValueError("Refuzat: qty trebuie să fie > 0")
        if client_order_id in self._submitted_ids:
            return {
                "status": "duplicate_skipped",
                "client_order_id": client_order_id,
                "symbol": symbol,
            }

        acct = self.get_account_state()
        resolved = resolve_execution_instrument(
            symbol=symbol,
            direction=direction,
            qty=qty,
            entry_price=entry_price,
            stop_price=stop_price,
            target_price=target_price,
            leverage=leverage,
            account_equity=acct["equity"],
            shorting_enabled=acct["shorting_enabled"],
            instrument_price=instrument_price,
        )

        order_payload = {
            "symbol": resolved["exec_symbol"],
            "side": resolved["side"],
            "qty": resolved["qty"],
            "stop_price": resolved["stop_price"],
            "target_price": resolved["target_price"],
            "client_order_id": client_order_id,
            "via_inverse_etf": resolved["via_inverse_etf"],
        }
        resp = self.client.submit_order(order_payload)
        self._submitted_ids.add(client_order_id)
        order_id = getattr(resp, "id", None) or (
            resp.get("id") if isinstance(resp, dict) else client_order_id
        )
        return {
            **order_payload,
            "id": str(order_id),
            "status": "submitted",
        }

    def submit_long_with_stop(
        self,
        symbol: str,
        qty: float,
        stop_price: float,
        client_order_id: str,
        entry_price: float | None = None,
    ) -> dict[str, Any]:
        """Convenience wrapper for a 1x long order with mandatory stop."""
        eff_entry = float(entry_price) if entry_price is not None else float(stop_price) * 1.005
        return self.submit_order_with_stop(
            symbol=symbol,
            direction="long",
            qty=qty,
            entry_price=eff_entry,
            stop_price=stop_price,
            client_order_id=client_order_id,
            leverage=1,
        )

    def liquidate_all(self) -> int:
        """Cancel all open orders and close all open positions immediately (KILL / EOD)."""
        open_pos = self.get_open_positions()
        if hasattr(self.client, "cancel_orders"):
            self.client.cancel_orders()
        if hasattr(self.client, "close_all_positions"):
            self.client.close_all_positions(cancel_orders=True)
        return len(open_pos)
