"""Offline Alpaca TradingClient simulator for live-runner tests (Faza B, B6d).

Unlike a dict-accepting stub it only accepts real alpaca-py request objects, so a payload that the
real `TradingClient.submit_order` would reject (e.g. a plain dict) fails here too.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import numpy as np
import pandas as pd
from alpaca.common.exceptions import APIError
from alpaca.trading.requests import (
    GetOrdersRequest,
    MarketOrderRequest,
    ReplaceOrderRequest,
    StopOrderRequest,
)


def _val(x: Any) -> str:
    return str(getattr(x, "value", x)).lower()


class FakeAlpaca:
    """Market orders fill instantly at `prices[symbol]`; stop orders rest until `trigger_stop`."""

    def __init__(
        self,
        prices: dict[str, float] | None = None,
        equity: float = 500.0,
        last_equity: float | None = None,
        fail_stop: bool = False,
    ) -> None:
        self.prices = dict(prices or {})
        self.equity = equity
        self.last_equity = equity if last_equity is None else last_equity
        self.fail_stop = fail_stop
        self.orders: dict[str, SimpleNamespace] = {}
        self.positions: dict[str, dict[str, float]] = {}
        self.submitted: list[Any] = []
        self.replaced: list[tuple[str, float]] = []
        self._n = 0

    # ---------------------------------------------------------------- account
    def get_account(self) -> SimpleNamespace:
        return SimpleNamespace(
            equity=str(self.equity),
            last_equity=str(self.last_equity),
            cash=str(self.equity),
            buying_power=str(self.equity),
            shorting_enabled=False,
            multiplier="1",
        )

    def get_all_positions(self) -> list[SimpleNamespace]:
        out = []
        for sym, p in self.positions.items():
            px = self.prices.get(sym, p["avg"])
            out.append(
                SimpleNamespace(
                    symbol=sym,
                    qty=str(p["qty"]),
                    side="long",
                    avg_entry_price=str(p["avg"]),
                    current_price=str(px),
                    market_value=str(p["qty"] * px),
                    unrealized_pl=str(p["qty"] * (px - p["avg"])),
                )
            )
        return out

    # ----------------------------------------------------------------- orders
    def _new_order(self, req: Any, otype: str) -> SimpleNamespace:
        self._n += 1
        o = SimpleNamespace(
            id=f"ord-{self._n}",
            client_order_id=req.client_order_id,
            symbol=req.symbol,
            side=_val(req.side),
            qty=float(req.qty),
            type=otype,
            stop_price=getattr(req, "stop_price", None),
            status="new",
            filled_qty="0",
            filled_avg_price=None,
            filled_at=None,
            submitted_at=datetime.now(UTC),
        )
        self.orders[o.id] = o
        return o

    def _fill(self, o: SimpleNamespace, price: float) -> None:
        o.status = "filled"
        o.filled_qty = str(o.qty)
        o.filled_avg_price = str(price)
        o.filled_at = datetime.now(UTC)
        pos = self.positions.get(o.symbol)
        if o.side == "buy":
            if pos is None:
                self.positions[o.symbol] = {"qty": o.qty, "avg": price}
            else:
                tot = pos["qty"] + o.qty
                pos["avg"] = (pos["avg"] * pos["qty"] + price * o.qty) / tot
                pos["qty"] = tot
        elif pos is not None:
            pos["qty"] -= o.qty
            if pos["qty"] <= 1e-9:
                del self.positions[o.symbol]

    def submit_order(self, order_data: Any) -> SimpleNamespace:
        if not isinstance(order_data, (MarketOrderRequest, StopOrderRequest)):
            raise AttributeError("submit_order needs an alpaca-py OrderRequest")
        if any(
            o.client_order_id == order_data.client_order_id
            for o in self.orders.values()
            if o.client_order_id
        ):
            raise APIError('{"code": 40010001, "message": "client_order_id must be unique"}')
        self.submitted.append(order_data)
        if isinstance(order_data, StopOrderRequest):
            if self.fail_stop:
                raise APIError('{"code": 42210000, "message": "stop rejected"}')
            stop = float(order_data.stop_price)
            if round(stop, 2) != stop:
                raise APIError('{"code": 42210000, "message": "sub-penny increment"}')
            return self._new_order(order_data, "stop")
        o = self._new_order(order_data, "market")
        self._fill(o, float(self.prices[order_data.symbol]))
        return o

    def get_order_by_id(self, order_id: str) -> SimpleNamespace:
        return self.orders[str(order_id)]

    def cancel_order_by_id(self, order_id: str) -> None:
        o = self.orders[str(order_id)]
        if o.status in ("new", "accepted"):
            o.status = "canceled"

    def replace_order_by_id(self, order_id: str, order_data: ReplaceOrderRequest) -> Any:
        old = self.orders[str(order_id)]
        old.status = "replaced"
        self._n += 1
        new = SimpleNamespace(**{**vars(old), "id": f"ord-{self._n}", "status": "new"})
        new.stop_price = float(order_data.stop_price)
        new.client_order_id = order_data.client_order_id or old.client_order_id
        self.orders[new.id] = new
        self.replaced.append((new.symbol, new.stop_price))
        return new

    def get_orders(self, filter: GetOrdersRequest | None = None) -> list[SimpleNamespace]:
        out = list(self.orders.values())
        if filter is not None and filter.symbols:
            out = [o for o in out if o.symbol in filter.symbols]
        if filter is not None and _val(filter.status) == "open":
            out = [o for o in out if o.status in ("new", "accepted")]
        if filter is not None and _val(filter.status) == "closed":
            out = [o for o in out if o.status not in ("new", "accepted")]
        return out

    def open_stop(self, symbol: str) -> SimpleNamespace | None:
        for o in self.orders.values():
            if o.symbol == symbol and o.type == "stop" and o.status == "new":
                return o
        return None

    def trigger_stop(self, symbol: str, price: float) -> None:
        o = self.open_stop(symbol)
        assert o is not None, f"no open stop on {symbol}"
        self._fill(o, price)

    def close_position(self, symbol: str) -> SimpleNamespace:
        pos = self.positions[symbol]
        req = MarketOrderRequest(symbol=symbol, qty=pos["qty"], side="sell", time_in_force="day")
        o = self._new_order(req, "market")
        self._fill(o, float(self.prices[symbol]))
        return o

    def cancel_orders(self) -> list[Any]:
        for o in self.orders.values():
            if o.status in ("new", "accepted"):
                o.status = "canceled"
        return []

    def close_all_positions(self, cancel_orders: bool = True) -> list[Any]:
        if cancel_orders:
            self.cancel_orders()
        for sym in list(self.positions):
            self.close_position(sym)
        return []


def make_intraday_bars(
    days: int = 16,
    breakout_last_day: str = "long",
    base: float = 580.0,
    cut_at_minute: int = 41,
    start: str = "2026-10-01",
) -> pd.DataFrame:
    """Synthetic NYSE session bars; the last day breaks out until 10:11 ET (minute 41).

    The returned frame ends at minute `cut_at_minute` of the last day (41 -> the 10:11 D1b
    check bar is the last bar).
    """
    sessions = pd.bdate_range(start, periods=days)
    rows: list[dict[str, float]] = []
    idx: list[pd.Timestamp] = []
    rng = np.random.default_rng(123)
    for d_i, day in enumerate(sessions):
        day_str = day.strftime("%Y-%m-%d")
        minutes = pd.date_range(
            f"{day_str} 09:30", f"{day_str} 15:59", freq="1min", tz="America/New_York"
        )
        for m_i, ts in enumerate(minutes):
            if d_i < days - 1:
                noise = 0.05 * np.sin(m_i / 10.0) + float(rng.normal(0, 0.02))
                c = base + noise
                o, h, low, vwap = c - 0.01, c + 0.04, c - 0.04, base
            else:
                if m_i > cut_at_minute:
                    break
                sign = {"long": 1.0, "short": -1.0}.get(breakout_last_day, 0.0)
                frac = min(m_i, 41) / 41.0
                c = base + sign * frac * 4.5
                vwap = base + sign * frac * 1.5
                o, h, low = c - 0.05, c + 0.10, c - 0.10
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
    return pd.DataFrame(rows, index=pd.DatetimeIndex(idx, name="timestamp"))
