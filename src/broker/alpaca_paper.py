"""Alpaca Paper/Live broker adapter with D31 Long+Short+Leverage mapping (Faza B, B5, B6d).

Safety & design guarantees:
1. Blocks `TRADING_MODE == "LIVE"` unless both `LIVE_APPROVED.md` exists and `reports/gate2.md`
   contains `PASS` (Rule 10, `AGENTS.md`).
2. Implements `resolve_execution_instrument` (D31): on a 500 $ account (`equity < 2000` or
   `shorting_enabled=False`), short signals on `SPY`/`QQQ` automatically route to fractional
   LONG buys on liquid inverse ETFs (`SH`/`SDS` for SPY, `PSQ`/`QID` for QQQ), and 2x long
   signals can route to `SSO`/`QLD`, preserving exact dollar risk and stop distance. The stop of
   a different instrument is always computed from that instrument's own price (D32).
3. Deterministic `client_order_id` (`make_client_order_id`) for idempotency on restart; a
   duplicate rejected by Alpaca is reported as `duplicate_skipped`, never as a crash.
4. Every entry is a real alpaca-py request: fractional MARKET order (TIF=DAY), wait for the fill,
   then a separate STOP order (TIF=DAY) for the filled quantity. Alpaca does not document
   bracket/OTO orders for fractional quantities, so the two-step flow is used. If the stop cannot
   be placed, the position is closed immediately (no position ever stays without a stop).
5. `liquidate_all()` cancels all open orders and closes all positions immediately.
"""

from __future__ import annotations

import math
import re
import time
from collections.abc import Callable, Iterable
from datetime import datetime
from pathlib import Path
from typing import Any

from alpaca.trading.enums import OrderSide, QueryOrderStatus, TimeInForce
from alpaca.trading.requests import (
    GetOrdersRequest,
    MarketOrderRequest,
    ReplaceOrderRequest,
    StopOrderRequest,
)

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

STOP_SUFFIX = "-SL"
FILLED_STATES = frozenset({"filled"})
DEAD_STATES = frozenset({"canceled", "expired", "rejected", "replaced", "done_for_day"})


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


def round_price(price: float) -> float:
    """Round to a valid US stock price increment (1 cent for prices >= 1 $)."""
    return round(float(price), 2) if float(price) >= 1.0 else round(float(price), 4)


def uses_inverse_etf(direction: str, account_equity: float, shorting_enabled: bool) -> bool:
    """True when a short signal must be executed by buying an inverse ETF (D31)."""
    return str(direction).lower() == "short" and (not shorting_enabled or account_equity < 2000.0)


def exec_symbol_for(
    symbol: str,
    direction: str,
    leverage: int = 1,
    account_equity: float = 500.0,
    shorting_enabled: bool = False,
) -> str:
    """Return the instrument actually traded for a signal on `symbol` (D31 mapping)."""
    sym = symbol.upper()
    lev = 2 if int(leverage) >= 2 else 1
    if uses_inverse_etf(direction, account_equity, shorting_enabled):
        return INVERSE_ETF_MAP.get((sym, lev), sym)
    if str(direction).lower() == "long":
        return LEVERAGED_LONG_ETF_MAP.get((sym, lev), sym)
    return sym


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
    with stop below entry. Preserves the planned dollar risk and caps notional to 50% of equity.
    `instrument_price` is mandatory whenever the executed ETF differs from `symbol`.
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
    exec_sym = exec_symbol_for(sym, dir_norm, lev, account_equity, shorting_enabled)
    if exec_sym != sym and (instrument_price is None or instrument_price <= 0):
        raise ValueError(f"Lipsește prețul curent pentru {exec_sym}; ordinul nu poate fi calculat")

    def _translated(via_inverse: bool) -> dict[str, Any]:
        exec_price = float(instrument_price if instrument_price is not None else entry_price)
        eff_dist_pct = min(0.20, raw_risk_pct * lev)
        exec_stop = round_price(exec_price * (1.0 - eff_dist_pct))
        exec_target = (
            round_price(exec_price * (1.0 + raw_tp_pct * lev)) if raw_tp_pct is not None else None
        )
        per_share_risk = max(exec_price - exec_stop, 1e-4)
        exec_qty = planned_risk_dollars / per_share_risk
        max_notional = max(0.0, account_equity * 0.5)
        if exec_qty * exec_price > max_notional and exec_price > 0:
            exec_qty = max_notional / exec_price
        return {
            "signal_symbol": sym,
            "signal_direction": dir_norm,
            "exec_symbol": exec_sym,
            "exec_direction": "long",
            "side": "buy",
            "qty": round(float(exec_qty), 6),
            "entry_price": exec_price,
            "stop_price": exec_stop,
            "target_price": exec_target,
            "leverage": lev,
            "via_inverse_etf": via_inverse,
        }

    # Case 1: Short signal on an account that cannot short directly (< 2000 $ or shorting disabled)
    if uses_inverse_etf(dir_norm, account_equity, shorting_enabled):
        return _translated(via_inverse=True)

    # Case 2: Long signal (1x SPY/QQQ or 2x SSO/QLD)
    if dir_norm == "long":
        if exec_sym != sym or instrument_price is not None:
            return _translated(via_inverse=False)
        return {
            "signal_symbol": sym,
            "signal_direction": "long",
            "exec_symbol": exec_sym,
            "exec_direction": "long",
            "side": "buy",
            "qty": round(float(qty), 6),
            "entry_price": float(entry_price),
            "stop_price": round_price(stop_price),
            "target_price": round_price(target_price) if target_price is not None else None,
            "leverage": lev,
            "via_inverse_etf": False,
        }

    # Case 3: Direct short on margin account (>= 2000 $ and shorting_enabled=True, whole shares)
    whole_qty = float(max(1, int(math.floor(qty))))
    return {
        "signal_symbol": sym,
        "signal_direction": "short",
        "exec_symbol": sym,
        "exec_direction": "short",
        "side": "sell",
        "qty": whole_qty,
        "entry_price": float(entry_price),
        "stop_price": round_price(stop_price),
        "target_price": round_price(target_price) if target_price is not None else None,
        "leverage": lev,
        "via_inverse_etf": False,
    }


def _status(order: Any) -> str:
    raw = getattr(order, "status", None)
    if raw is None and isinstance(order, dict):
        raw = order.get("status")
    raw = getattr(raw, "value", raw)
    return str(raw or "").lower()


def _field(order: Any, name: str, default: Any = None) -> Any:
    if isinstance(order, dict):
        return order.get(name, default)
    return getattr(order, name, default)


def _float(value: Any, default: float = 0.0) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return default
    return out if math.isfinite(out) else default


def _is_duplicate_error(exc: Exception) -> bool:
    text = str(exc).lower()
    return "client_order_id" in text and ("unique" in text or "duplicate" in text)


class AlpacaPaperAdapter:
    """Safe wrapper over Alpaca TradingClient for Paper (and gated Live) execution."""

    def __init__(
        self,
        trading_client: Any,
        trading_mode: str | None = None,
        root_dir: Path | str = ".",
        *,
        sleep: Callable[[float], None] = time.sleep,
        fill_timeout_s: float = 20.0,
        poll_interval_s: float = 1.0,
    ) -> None:
        assert_live_mode_allowed(trading_mode=trading_mode, root_dir=root_dir)
        self.client = trading_client
        self.trading_mode = (trading_mode or settings.TRADING_MODE).upper()
        self._submitted_ids: set[str] = set()
        self._sleep = sleep
        self.fill_timeout_s = float(fill_timeout_s)
        self.poll_interval_s = float(poll_interval_s)

    # ----------------------------------------------------------------- account / positions
    def get_account_state(self) -> dict[str, Any]:
        acct = self.client.get_account()
        equity = _float(getattr(acct, "equity", 0.0))
        return {
            "equity": equity,
            "last_equity": _float(getattr(acct, "last_equity", equity), equity),
            "cash": _float(getattr(acct, "cash", 0.0)),
            "buying_power": _float(getattr(acct, "buying_power", 0.0)),
            "shorting_enabled": bool(getattr(acct, "shorting_enabled", False)),
            "multiplier": int(_float(getattr(acct, "multiplier", 1) or 1, 1.0)),
        }

    def get_open_positions(self) -> dict[str, dict[str, Any]]:
        raw_positions = self.client.get_all_positions()
        out: dict[str, dict[str, Any]] = {}
        for p in raw_positions:
            sym = str(getattr(p, "symbol", "")).upper()
            qty = _float(getattr(p, "qty", 0.0))
            side = str(getattr(getattr(p, "side", "long"), "value", getattr(p, "side", "long")))
            direction = "short" if "short" in side.lower() or qty < 0 else "long"
            entry_p = _float(getattr(p, "avg_entry_price", 0.0))
            curr_p = _float(getattr(p, "current_price", entry_p), entry_p)
            out[sym] = {
                "symbol": sym,
                "direction": direction,
                "qty": abs(qty),
                "entry_price": entry_p,
                "current_price": curr_p,
                "market_value": abs(_float(getattr(p, "market_value", abs(qty) * curr_p))),
                "unrealized_pnl": _float(getattr(p, "unrealized_pl", 0.0)),
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

    # ----------------------------------------------------------------------------- orders
    def _wait_for_fill(self, order_id: str) -> Any:
        """Poll an order until it is filled, dead, or the timeout expires."""
        waited = 0.0
        order = self.client.get_order_by_id(order_id)
        while _status(order) not in FILLED_STATES | DEAD_STATES and waited < self.fill_timeout_s:
            self._sleep(self.poll_interval_s)
            waited += self.poll_interval_s
            order = self.client.get_order_by_id(order_id)
        return order

    def _submit_stop(
        self, symbol: str, qty: float, stop_price: float, side: OrderSide, client_order_id: str
    ) -> Any:
        req = StopOrderRequest(
            symbol=symbol,
            qty=round(float(qty), 9),
            side=side,
            time_in_force=TimeInForce.DAY,
            stop_price=round_price(stop_price),
            client_order_id=client_order_id,
        )
        return self.client.submit_order(req)

    def submit_entry_with_stop(
        self,
        *,
        symbol: str,
        qty: float,
        stop_price: float,
        client_order_id: str,
        side: str = "buy",
    ) -> dict[str, Any]:
        """Market entry (fractional, DAY) + separate protective STOP for the filled quantity."""
        if stop_price is None or not math.isfinite(stop_price) or stop_price <= 0:
            raise ValueError("Refuzat: orice ordin trebuie să aibă un stop_price > 0 valid")
        if qty <= 0:
            raise ValueError("Refuzat: qty trebuie să fie > 0")
        sym = symbol.upper()
        base = {"symbol": sym, "client_order_id": client_order_id, "side": side}
        if client_order_id in self._submitted_ids:
            return {**base, "status": "duplicate_skipped"}

        entry_side = OrderSide.BUY if side == "buy" else OrderSide.SELL
        exit_side = OrderSide.SELL if side == "buy" else OrderSide.BUY
        req = MarketOrderRequest(
            symbol=sym,
            qty=round(float(qty), 9),
            side=entry_side,
            time_in_force=TimeInForce.DAY,
            client_order_id=client_order_id,
        )
        try:
            order = self.client.submit_order(req)
        except Exception as exc:  # noqa: BLE001
            if _is_duplicate_error(exc):
                self._submitted_ids.add(client_order_id)
                return {**base, "status": "duplicate_skipped"}
            return {**base, "status": "rejected", "error": str(exc)[:200]}
        self._submitted_ids.add(client_order_id)
        order_id = str(_field(order, "id", client_order_id))

        filled = self._wait_for_fill(order_id)
        filled_qty = _float(_field(filled, "filled_qty", 0.0))
        fill_price = _float(_field(filled, "filled_avg_price", 0.0))
        if _status(filled) not in FILLED_STATES:
            # Partial or no fill after the timeout: cancel the rest, protect what was filled
            try:
                self.client.cancel_order_by_id(order_id)
            except Exception:  # noqa: BLE001
                pass
        if filled_qty <= 0 or fill_price <= 0:
            return {**base, "id": order_id, "status": "not_filled", "qty": 0.0}

        stop_ok = (side == "buy" and stop_price < fill_price) or (
            side != "buy" and stop_price > fill_price
        )
        if not stop_ok:
            self.close_position(sym)
            return {
                **base,
                "id": order_id,
                "status": "closed_invalid_stop",
                "qty": filled_qty,
                "filled_avg_price": fill_price,
                "error": "Prețul de execuție a trecut deja de stop; poziția a fost închisă.",
            }
        try:
            stop_order = self._submit_stop(
                sym, filled_qty, stop_price, exit_side, client_order_id + STOP_SUFFIX
            )
        except Exception as exc:  # noqa: BLE001
            self.close_position(sym)
            return {
                **base,
                "id": order_id,
                "status": "closed_stop_failed",
                "qty": filled_qty,
                "filled_avg_price": fill_price,
                "error": str(exc)[:200],
            }
        return {
            **base,
            "id": order_id,
            "status": "filled",
            "qty": filled_qty,
            "filled_avg_price": fill_price,
            "filled_at": str(_field(filled, "filled_at", "") or ""),
            "stop_price": round_price(stop_price),
            "stop_order_id": str(_field(stop_order, "id", "")),
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
        """Resolve a raw SPY/QQQ signal via D31 and submit it with a mandatory stop-loss."""
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
        res = self.submit_entry_with_stop(
            symbol=resolved["exec_symbol"],
            qty=resolved["qty"],
            stop_price=resolved["stop_price"],
            client_order_id=client_order_id,
            side=resolved["side"],
        )
        return {
            **res,
            "target_price": resolved["target_price"],
            "via_inverse_etf": resolved["via_inverse_etf"],
            "stop_price": resolved["stop_price"],
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

    def get_open_orders(self, symbols: Iterable[str] | None = None) -> list[dict[str, Any]]:
        req = GetOrdersRequest(
            status=QueryOrderStatus.OPEN,
            symbols=[s.upper() for s in symbols] if symbols else None,
        )
        out: list[dict[str, Any]] = []
        for o in self.client.get_orders(filter=req) or []:
            out.append(
                {
                    "id": str(_field(o, "id", "")),
                    "client_order_id": str(_field(o, "client_order_id", "")),
                    "symbol": str(_field(o, "symbol", "")).upper(),
                    "side": str(getattr(_field(o, "side", ""), "value", _field(o, "side", ""))),
                    "qty": _float(_field(o, "qty", 0.0)),
                    "stop_price": _float(_field(o, "stop_price", 0.0)),
                    "status": _status(o),
                }
            )
        return out

    def get_filled_orders(
        self, after: datetime, symbols: Iterable[str] | None = None
    ) -> list[dict[str, Any]]:
        """Filled (or partially filled) orders since `after`, oldest first."""
        req = GetOrdersRequest(
            status=QueryOrderStatus.CLOSED,
            after=after,
            symbols=[s.upper() for s in symbols] if symbols else None,
            limit=500,
        )
        out: list[dict[str, Any]] = []
        for o in self.client.get_orders(filter=req) or []:
            f_qty = _float(_field(o, "filled_qty", 0.0))
            if f_qty <= 0:
                continue
            out.append(
                {
                    "id": str(_field(o, "id", "")),
                    "client_order_id": str(_field(o, "client_order_id", "")),
                    "symbol": str(_field(o, "symbol", "")).upper(),
                    "side": str(getattr(_field(o, "side", ""), "value", _field(o, "side", ""))),
                    "filled_qty": f_qty,
                    "filled_avg_price": _float(_field(o, "filled_avg_price", 0.0)),
                    "filled_at": str(_field(o, "filled_at", "") or ""),
                }
            )
        out.sort(key=lambda r: r["filled_at"])
        return out

    def cancel_symbol_orders(self, symbol: str) -> int:
        n = 0
        for o in self.get_open_orders([symbol]):
            try:
                self.client.cancel_order_by_id(o["id"])
                n += 1
            except Exception:  # noqa: BLE001
                pass
        return n

    def close_position(self, symbol: str) -> bool:
        """Cancel open orders on `symbol`, then close the position at market."""
        sym = symbol.upper()
        if self.cancel_symbol_orders(sym):
            self._sleep(self.poll_interval_s)
        try:
            self.client.close_position(sym)
            return True
        except Exception:  # noqa: BLE001
            return False

    def replace_stop(
        self,
        *,
        symbol: str,
        stop_order_id: str,
        qty: float,
        new_stop: float,
        client_order_id: str,
        side: str = "sell",
    ) -> dict[str, Any]:
        """Tighten the protective stop; falls back to cancel + new stop, then to closing."""
        try:
            # Keep a "-SL" client_order_id so a later stop fill is classified as "stop"
            resp = self.client.replace_order_by_id(
                stop_order_id,
                ReplaceOrderRequest(
                    stop_price=round_price(new_stop), client_order_id=client_order_id
                ),
            )
            return {"status": "replaced", "stop_order_id": str(_field(resp, "id", stop_order_id))}
        except Exception:  # noqa: BLE001
            pass
        try:
            self.client.cancel_order_by_id(stop_order_id)
        except Exception:  # noqa: BLE001
            pass
        try:
            resp = self._submit_stop(
                symbol,
                qty,
                new_stop,
                OrderSide.SELL if side == "sell" else OrderSide.BUY,
                client_order_id,
            )
            return {"status": "resubmitted", "stop_order_id": str(_field(resp, "id", ""))}
        except Exception as exc:  # noqa: BLE001
            closed = self.close_position(symbol)
            return {"status": "closed_stop_failed" if closed else "error", "error": str(exc)[:200]}

    def sell_partial(
        self,
        *,
        symbol: str,
        qty_to_sell: float,
        remaining_qty: float,
        new_stop: float,
        client_order_id: str,
    ) -> dict[str, Any]:
        """Take partial profit: cancel the stop, sell part at market, re-protect the rest."""
        sym = symbol.upper()
        self.cancel_symbol_orders(sym)
        self._sleep(self.poll_interval_s)
        try:
            order = self.client.submit_order(
                MarketOrderRequest(
                    symbol=sym,
                    qty=round(float(qty_to_sell), 9),
                    side=OrderSide.SELL,
                    time_in_force=TimeInForce.DAY,
                    client_order_id=client_order_id,
                )
            )
            filled = self._wait_for_fill(str(_field(order, "id", "")))
        except Exception as exc:  # noqa: BLE001
            filled = None
            err = str(exc)[:200]
        else:
            err = ""
        sold = _float(_field(filled, "filled_qty", 0.0)) if filled is not None else 0.0
        # Re-protect whatever is still held (the full position if the partial sale failed)
        stop_qty = max(0.0, float(qty_to_sell) + float(remaining_qty) - sold)
        try:
            stop_order = self._submit_stop(
                sym, stop_qty, new_stop, OrderSide.SELL, client_order_id + STOP_SUFFIX
            )
        except Exception as exc:  # noqa: BLE001
            self.close_position(sym)
            return {"status": "closed_stop_failed", "error": str(exc)[:200]}
        return {
            "status": "partial_filled" if sold > 0 else "partial_failed",
            "filled_qty": sold,
            "filled_avg_price": (
                _float(_field(filled, "filled_avg_price", 0.0)) if filled is not None else 0.0
            ),
            "remaining_qty": stop_qty,
            "stop_order_id": str(_field(stop_order, "id", "")),
            "error": err,
        }

    def liquidate_all(self) -> int:
        """Cancel all open orders and close all open positions immediately (KILL / EOD)."""
        open_pos = self.get_open_positions()
        if hasattr(self.client, "cancel_orders"):
            self.client.cancel_orders()
        if hasattr(self.client, "close_all_positions"):
            self.client.close_all_positions(cancel_orders=True)
        return len(open_pos)

    def wait_until_flat(self, timeout_s: float = 20.0) -> bool:
        """Poll positions until none remain (fills after `liquidate_all` are asynchronous)."""
        waited = 0.0
        while self.get_open_positions():
            if waited >= timeout_s:
                return False
            self._sleep(self.poll_interval_s)
            waited += self.poll_interval_s
        return True
