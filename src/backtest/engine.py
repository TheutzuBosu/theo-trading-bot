"""Bar-by-bar backtest engine.

Timeline of bar d:
1. Open: positions gapping through the stop (or target) exit at the Open, not at the level;
   exits signaled at the close of d-1 execute at the Open.
2. Open: entries signaled at the close of d-1 fill at the Open + costs; stop = fill - stop_distance;
   size via the risk-guard sizing (risk, max notional, max positions, max per sector, no leverage).
3. Intrabar: Low <= stop -> exit at the stop; High >= target -> exit at the target. If both are
   touched in the same bar, the stop wins (worst case).
4. Close: mark to market; time exits, delisting and the end of the window are handled here.
5. Close: read the signals of bar d; they execute at the Open of d+1.
Costs apply on every side: price * (1 +/- (slippage + half_spread)) plus a fixed commission.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from src.backtest.panel import MarketPanel, SignalPanel
from src.backtest.sizing import DEFAULT_RISK_PER_TRADE, portfolio_rejection, size_position


@dataclass(frozen=True)
class CostModel:
    slippage: float = 0.001
    half_spread: float = 0.0005
    commission: float = 0.0  # dollars per order

    @property
    def per_side(self) -> float:
        return self.slippage + self.half_spread

    def buy_price(self, price: float) -> float:
        return price * (1.0 + self.per_side)

    def sell_price(self, price: float) -> float:
        return price * (1.0 - self.per_side)


@dataclass(frozen=True)
class BacktestConfig:
    initial_capital: float = 500.0
    risk_per_trade: float = DEFAULT_RISK_PER_TRADE
    costs: CostModel = field(default_factory=CostModel)
    max_hold_bars: int | None = None  # time exit after this many bars held
    whole_shares: bool = False
    min_notional: float = 1.0
    record_rejections: bool = True


@dataclass
class BacktestResult:
    equity: pd.Series
    exposure: pd.Series  # market value of positions / equity, at each close
    trades: pd.DataFrame
    rejections: pd.DataFrame
    config: BacktestConfig


@dataclass
class _Position:
    sym: int
    entry_bar: int
    signal_bar: int
    qty: float
    entry_fill: float
    stop: float
    target: float
    risk_per_share: float
    cost_basis: float
    equity_at_entry: float
    mark: float
    low: float
    high: float
    bars_held: int = 0


class _Simulator:
    def __init__(self, panel, signals, config, sectors):
        self.p = panel
        self.s = signals
        self.cfg = config
        self.costs = config.costs
        self.sector = [sectors.get(sym, "UNKNOWN") for sym in panel.symbols]
        self.cash = config.initial_capital
        self.positions: dict[int, _Position] = {}
        self.trades: list[dict] = []
        self.rejections: list[dict] = []

    def _reject(self, d: int, j: int, reason: str) -> None:
        if self.cfg.record_rejections:
            self.rejections.append(
                {"date": self.p.dates[d], "symbol": self.p.symbols[j], "reason": reason}
            )

    def _close(self, j: int, d: int, price: float, reason: str) -> None:
        pos = self.positions.pop(j)
        fill = self.costs.sell_price(price)
        proceeds = pos.qty * fill - self.costs.commission
        self.cash += proceeds
        pnl = proceeds - pos.cost_basis
        risk = pos.qty * pos.risk_per_share
        reason_text = "" if self.s.entry_reason is None else self.s.entry_reason[pos.signal_bar, j]
        self.trades.append(
            {
                "symbol": self.p.symbols[j],
                "sector": self.sector[j],
                "signal_date": self.p.dates[pos.signal_bar],
                "entry_date": self.p.dates[pos.entry_bar],
                "entry_price": pos.entry_fill,
                "exit_date": self.p.dates[d],
                "exit_price": fill,
                "qty": pos.qty,
                "stop": pos.stop,
                "target": pos.target if np.isfinite(pos.target) else np.nan,
                "pnl": pnl,
                "return_pct": fill / pos.entry_fill - 1.0,
                "r_multiple": pnl / risk,
                "mae_r": (pos.low - pos.entry_fill) / pos.risk_per_share,
                "mfe_r": (pos.high - pos.entry_fill) / pos.risk_per_share,
                "bars_held": pos.bars_held,
                "equity_at_entry": pos.equity_at_entry,
                "exit_reason": reason,
                "entry_reason": reason_text,
            }
        )

    def _open_exits(self, d: int, pending_exits: dict[int, str]) -> None:
        o = self.p.open[d]
        for j in list(self.positions):
            pos = self.positions[j]
            if np.isnan(o[j]):
                continue
            if o[j] <= pos.stop:
                reason = "stop_gap"
            elif o[j] >= pos.target:
                reason = "target_gap"
            else:
                reason = pending_exits.get(j)
            if reason is not None:
                pos.low, pos.high = min(pos.low, o[j]), max(pos.high, o[j])
                self._close(j, d, o[j], reason)
                pending_exits.pop(j, None)

    def _open_entries(self, d: int, pending: list[int]) -> None:
        o = self.p.open[d]
        equity = self.cash + sum(
            pos.qty * (o[j] if np.isfinite(o[j]) else pos.mark) for j, pos in self.positions.items()
        )
        for j in pending:
            if j in self.positions:
                self._reject(d, j, "already_held")
                continue
            if np.isnan(o[j]):
                self._reject(d, j, "no_data")
                continue
            in_sector = sum(1 for k in self.positions if self.sector[k] == self.sector[j])
            limit = portfolio_rejection(len(self.positions), in_sector)
            if limit is not None:
                self._reject(d, j, limit)
                continue
            fill = self.costs.buy_price(o[j])
            stop = fill - self.s.stop_distance[d - 1, j]
            qty = size_position(fill, stop, equity, self.cfg.risk_per_trade)
            if qty <= 0:
                self._reject(d, j, "invalid_stop")
                continue
            qty = min(qty, max(self.cash - self.costs.commission, 0.0) / fill)
            if self.cfg.whole_shares:
                qty = float(np.floor(qty))
            if qty * fill < max(self.cfg.min_notional, 1e-12):
                self._reject(d, j, "qty_too_small")
                continue
            cost_basis = qty * fill + self.costs.commission
            self.cash -= cost_basis
            target_dist = self.s.target_distance[d - 1, j]
            self.positions[j] = _Position(
                sym=j,
                entry_bar=d,
                signal_bar=d - 1,
                qty=qty,
                entry_fill=fill,
                stop=stop,
                target=fill + target_dist if np.isfinite(target_dist) else np.inf,
                risk_per_share=fill - stop,
                cost_basis=cost_basis,
                equity_at_entry=equity,
                mark=o[j],
                low=o[j],
                high=o[j],
            )

    def _intrabar(self, d: int) -> None:
        o, h, lo = self.p.open[d], self.p.high[d], self.p.low[d]
        for j in list(self.positions):
            pos = self.positions[j]
            if np.isnan(lo[j]) or np.isnan(h[j]):
                continue
            if lo[j] <= pos.stop:  # worst case: the stop wins even if the target was touched
                pos.low = min(pos.low, pos.stop)
                pos.high = max(pos.high, o[j])
                self._close(j, d, pos.stop, "stop")
            elif h[j] >= pos.target:
                pos.low = min(pos.low, o[j])
                pos.high = max(pos.high, pos.target)
                self._close(j, d, pos.target, "target")
            else:
                pos.low = min(pos.low, lo[j])
                pos.high = max(pos.high, h[j])

    def run(self, i0: int, i1: int) -> BacktestResult:
        n = i1 - i0 + 1
        equity = np.empty(n)
        exposure = np.empty(n)
        pending_entries: list[int] = []
        pending_exits: dict[int, str] = {}
        max_hold = self.cfg.max_hold_bars

        for d in range(i0, i1 + 1):
            self._open_exits(d, pending_exits)
            if pending_entries:
                self._open_entries(d, pending_entries)
                pending_entries = []
            self._intrabar(d)

            c = self.p.close[d]
            for j, pos in self.positions.items():
                if np.isfinite(c[j]):
                    pos.mark = c[j]
                    pos.bars_held += 1
            for j in list(self.positions):
                if d == i1:
                    self._close(j, d, self.positions[j].mark, "end")
                elif d == self.p.last_valid[j]:
                    self._close(j, d, self.positions[j].mark, "delisted")

            market_value = sum(pos.qty * pos.mark for pos in self.positions.values())
            equity[d - i0] = self.cash + market_value
            exposure[d - i0] = market_value / equity[d - i0] if equity[d - i0] > 0 else 0.0
            if d == i1:
                break

            # keep only exits still pending for held positions (Open was missing)
            pending_exits = {j: r for j, r in pending_exits.items() if j in self.positions}
            for j, pos in self.positions.items():
                if self.s.exit[d, j]:
                    pending_exits[j] = "signal"
                elif max_hold is not None and pos.bars_held >= max_hold:
                    pending_exits[j] = "time"
            candidates = np.flatnonzero(self.s.entry[d] & np.isfinite(self.p.close[d]))
            if len(candidates):
                score = np.nan_to_num(self.s.score[d, candidates], nan=-np.inf)
                order = np.lexsort((candidates, -score))  # by score desc, then symbol order
                pending_entries = candidates[order].tolist()

        dates = self.p.dates[i0 : i1 + 1]
        return BacktestResult(
            equity=pd.Series(equity, index=dates, name="equity"),
            exposure=pd.Series(exposure, index=dates, name="exposure"),
            trades=pd.DataFrame(self.trades, columns=TRADE_COLUMNS),
            rejections=pd.DataFrame(self.rejections, columns=["date", "symbol", "reason"]),
            config=self.cfg,
        )


TRADE_COLUMNS = [
    "symbol",
    "sector",
    "signal_date",
    "entry_date",
    "entry_price",
    "exit_date",
    "exit_price",
    "qty",
    "stop",
    "target",
    "pnl",
    "return_pct",
    "r_multiple",
    "mae_r",
    "mfe_r",
    "bars_held",
    "equity_at_entry",
    "exit_reason",
    "entry_reason",
]


def run_backtest(
    panel: MarketPanel,
    signals: SignalPanel,
    config: BacktestConfig | None = None,
    sectors: Mapping[str, str] | None = None,
    start=None,
    end=None,
) -> BacktestResult:
    """Simulate the signals on [start, end]. Open positions are closed at the last close."""
    i0, i1 = panel.index_range(start, end)
    sim = _Simulator(panel, signals, config or BacktestConfig(), sectors or {})
    return sim.run(i0, i1)
