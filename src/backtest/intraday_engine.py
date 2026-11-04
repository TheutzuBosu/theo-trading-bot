"""Minute-by-minute intraday backtest engine for Faza B (SPY/QQQ, D24-D27).

Timeline of minute bar i of a symbol (NY time, bars labelled by their start minute):
1. Open: stop updates signaled at the close of the previous bar apply (a stop only tightens).
   Exits signaled at the previous bar fill at the Open; a position whose stop (or target) was
   gapped through exits at the Open, not at the level.
2. Open: entries signaled at the previous bar fill at the Open + costs, after the checks:
   one position per symbol, long_only, FOMC veto, stop on the losing side of the Open,
   initial risk >= 2x the round-trip cost, sizing capped by the exposure limit.
3. Intrabar: Low/High through the stop -> exit at the stop; through the target -> exit
   `target_fraction` of the position at the target. Both in the same bar -> stop (worst case).
4. Close: mark to market. At the symbol's last bar of the session (15:59, 12:59 on early closes,
   earlier when bars are missing, D26) every position exits at the Close (market on close).
5. Close: read the signals of the bar; they act at the Open of the symbol's next bar in the same
   session. Orders never carry over to the next session; signals on the last bar are ignored.
Costs per side, in dollars per share, come from src/backtest/intraday_costs.py.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass

import numpy as np
import pandas as pd

from src.backtest.fomc import fomc_blocked
from src.backtest.intraday_costs import Variant, cost_per_side, r_multiple, trade_allowed

SIGNAL_COLUMNS = (
    "entry",
    "stop",
    "target",
    "size",
    "exit",
    "exit_long",
    "exit_short",
    "stop_long",
    "stop_short",
    "stop_after_target",
)
PRICE_COLUMNS = ("open", "high", "low", "close")


@dataclass(frozen=True)
class IntradayPanel:
    timestamps: pd.DatetimeIndex  # union of the symbols' minute bars, NY time
    symbols: tuple[str, ...]
    open: np.ndarray  # [bars, symbols], NaN = no bar
    high: np.ndarray
    low: np.ndarray
    close: np.ndarray
    sessions: pd.DatetimeIndex  # session dates
    bounds: np.ndarray  # [sessions, 2]: first and last bar of each session (inclusive)
    last_bar: np.ndarray  # [sessions, symbols]: last bar with a close, -1 if none

    @classmethod
    def from_frames(cls, bars: Mapping[str, pd.DataFrame]) -> IntradayPanel:
        """Align regular-session minute bars on the union of their timestamps."""
        symbols = tuple(sorted(bars))
        if not symbols:
            raise ValueError("No minute bars")
        ts = pd.DatetimeIndex(sorted(set().union(*(bars[s].index for s in symbols))))
        if ts.tz is None:
            raise ValueError("minute bars must have a timezone-aware index")
        arrays = {
            col: np.column_stack([bars[s][col].reindex(ts).to_numpy(dtype=float) for s in symbols])
            for col in PRICE_COLUMNS
        }
        days = ts.tz_localize(None).normalize()
        starts = np.flatnonzero(np.r_[True, days[1:] != days[:-1]])
        ends = np.r_[starts[1:] - 1, len(ts) - 1]
        has_close = np.isfinite(arrays["close"])
        idx = np.where(has_close, np.arange(len(ts))[:, None], -1)
        last_bar = np.maximum.reduceat(idx, starts, axis=0)
        return cls(
            timestamps=ts,
            symbols=symbols,
            sessions=pd.DatetimeIndex(days[starts], name="session"),
            bounds=np.column_stack([starts, ends]),
            last_bar=last_bar,
            **arrays,
        )

    def session_range(self, start=None, end=None) -> tuple[int, int]:
        """Inclusive range [s0, s1] of the sessions between the dates start and end."""
        s0 = 0 if start is None else int(self.sessions.searchsorted(pd.Timestamp(start), "left"))
        s1 = (
            len(self.sessions) - 1
            if end is None
            else int(self.sessions.searchsorted(pd.Timestamp(end), "right")) - 1
        )
        if s0 > s1:
            raise ValueError(f"Empty backtest window: {start} .. {end}")
        return s0, s1


@dataclass(frozen=True)
class IntradaySignals:
    """Signals read at the close of bar t, computed only from bars <= t.

    - entry (int, required): +1 long, -1 short, 0 nothing; fills at the next bar's Open.
    - stop (float, required with an entry): initial stop price; the broker always holds a stop.
    - target (float): target price for the entry, NaN = none.
    - size (float): wanted notional / equity (volatility target); NaN = size by risk_per_trade.
    - exit (bool): close the open position at the next bar's Open.
    - exit_long, exit_short (bool): close only an open long / short at the next bar's Open.
    - stop_long, stop_short (float): new stop for an open long / short (trailing); NaN = keep.
    - stop_after_target (float): new stop applied after a partial exit at target (only tightens).
    - entry_reason (str): why the entry fired, copied to the trade log.
    """

    entry: np.ndarray
    stop: np.ndarray
    target: np.ndarray
    size: np.ndarray
    exit: np.ndarray
    exit_long: np.ndarray
    exit_short: np.ndarray
    stop_long: np.ndarray
    stop_short: np.ndarray
    stop_after_target: np.ndarray
    entry_reason: np.ndarray | None = None

    @classmethod
    def from_frames(
        cls, signals: Mapping[str, pd.DataFrame], panel: IntradayPanel
    ) -> IntradaySignals:
        """Align per-symbol signal frames to the panel; symbols without signals never trade."""
        missing = [s for s in signals if s not in panel.symbols]
        if missing:
            raise ValueError(f"Signals for symbols without prices: {missing}")
        for sym, frame in signals.items():
            for col in ("entry", "stop"):
                if col not in frame.columns:
                    raise ValueError(f"[{sym}] signal column '{col}' is required")

        def column(name: str, fill, dtype) -> np.ndarray:
            cols = []
            for sym in panel.symbols:
                frame = signals.get(sym)
                if frame is None or name not in frame.columns:
                    cols.append(np.full(len(panel.timestamps), fill, dtype=dtype))
                else:
                    series = frame[name].reindex(panel.timestamps)
                    cols.append(series.where(series.notna(), fill).to_numpy(dtype=dtype))
            return np.column_stack(cols)

        entry = column("entry", 0, np.int8)
        if not np.isin(entry, (-1, 0, 1)).all():
            raise ValueError("entry must be -1, 0 or +1")
        has_reason = any("entry_reason" in f.columns for f in signals.values())
        return cls(
            entry=entry,
            stop=column("stop", np.nan, float),
            target=column("target", np.nan, float),
            size=column("size", np.nan, float),
            exit=column("exit", False, bool),
            exit_long=column("exit_long", False, bool),
            exit_short=column("exit_short", False, bool),
            stop_long=column("stop_long", np.nan, float),
            stop_short=column("stop_short", np.nan, float),
            stop_after_target=column("stop_after_target", np.nan, float),
            entry_reason=column("entry_reason", "", object) if has_reason else None,
        )


@dataclass(frozen=True)
class IntradayConfig:
    initial_capital: float = 500.0
    cost_variant: Variant = "stock"
    cost_stress: float = 1.0
    long_only: bool = False
    max_exposure: float = 2.0  # notional / equity over all symbols; 1.0 without margin (D24)
    risk_per_trade: float = 0.005  # sizing when a signal has no `size`
    max_risk_per_trade: float | None = None  # cap on qty * initial risk / equity
    target_fraction: float = 1.0  # part of the position closed at the target (D1b: 0.5)
    fomc_veto: bool = True
    whole_shares: bool = False
    min_notional: float = 1.0
    record_rejections: bool = True


@dataclass
class IntradayResult:
    equity: pd.Series  # bot equity at each session close (always flat then)
    trades: pd.DataFrame
    rejections: pd.DataFrame
    config: IntradayConfig


@dataclass
class _Position:
    sym: int
    direction: int  # +1 long, -1 short
    signal_bar: int
    entry_bar: int
    qty0: float
    qty: float  # still open
    entry_open: float  # raw Open of the entry bar; R is measured from it
    entry_fill: float
    initial_stop: float
    stop: float
    target: float
    initial_risk: float  # per share: |entry_open - initial_stop|
    equity_at_entry: float
    mark: float
    worst: float  # most adverse price while held
    best: float
    exit_qty_value: float = 0.0  # sum of exit qty * fill
    exit_raw_value: float = 0.0  # sum of exit qty * price before costs
    partial: bool = False
    stop_after_target: float = math.nan


TRADE_COLUMNS = [
    "symbol",
    "direction",
    "signal_time",
    "entry_time",
    "entry_open",
    "entry_price",
    "exit_time",
    "exit_raw",
    "exit_price",
    "qty",
    "initial_stop",
    "stop",
    "target",
    "initial_risk",
    "risk_pct",
    "notional_pct",
    "pnl",
    "r_multiple",
    "mae_r",
    "mfe_r",
    "bars_held",
    "equity_at_entry",
    "exit_reason",
    "exit_at_open",
    "partial_exit",
    "entry_reason",
    "entry_bar",
    "exit_bar",
]
AT_OPEN_REASONS = ("signal", "stop_gap", "target_gap")


class _Simulator:
    def __init__(self, panel: IntradayPanel, signals: IntradaySignals, config: IntradayConfig):
        self.p = panel
        self.s = signals
        self.cfg = config
        k = len(panel.symbols)
        self.cost = [
            cost_per_side(sym, config.cost_variant, config.cost_stress) for sym in panel.symbols
        ]
        # per-symbol Python lists: scalar access is much faster than on numpy arrays
        self.o = [panel.open[:, j].tolist() for j in range(k)]
        self.h = [panel.high[:, j].tolist() for j in range(k)]
        self.lo = [panel.low[:, j].tolist() for j in range(k)]
        self.c = [panel.close[:, j].tolist() for j in range(k)]
        self.ent = [signals.entry[:, j].tolist() for j in range(k)]
        self.ext = [signals.exit[:, j].tolist() for j in range(k)]
        self.ext_dir = {
            1: [signals.exit_long[:, j].tolist() for j in range(k)],
            -1: [signals.exit_short[:, j].tolist() for j in range(k)],
        }
        self.trail = {
            1: [signals.stop_long[:, j].tolist() for j in range(k)],
            -1: [signals.stop_short[:, j].tolist() for j in range(k)],
        }
        self.blocked = (
            fomc_blocked(panel.timestamps) if config.fomc_veto else np.zeros(len(panel.timestamps))
        ).tolist()
        self.cash = config.initial_capital
        self.positions: dict[int, _Position] = {}
        self.trades: list[dict] = []
        self.rejections: list[dict] = []

    # --- helpers -----------------------------------------------------------------------------
    def _reject(self, i: int, j: int, direction: int, reason: str) -> None:
        if self.cfg.record_rejections:
            self.rejections.append(
                {
                    "time": self.p.timestamps[i],
                    "symbol": self.p.symbols[j],
                    "direction": direction,
                    "reason": reason,
                }
            )

    def _equity(self) -> float:
        return self.cash + sum(p.direction * p.qty * p.mark for p in self.positions.values())

    def _exit(self, j: int, i: int, price: float, qty: float, reason: str) -> None:
        """Close `qty` shares of the position at `price` (before costs)."""
        pos = self.positions[j]
        d = pos.direction
        fill = price - d * self.cost[j]
        self.cash += d * qty * fill
        pos.exit_qty_value += qty * fill
        pos.exit_raw_value += qty * price
        pos.qty -= qty
        if d == 1:
            pos.worst, pos.best = min(pos.worst, price), max(pos.best, price)
        else:
            pos.worst, pos.best = max(pos.worst, price), min(pos.best, price)
        if pos.qty > 1e-12:
            pos.partial = True
            return
        del self.positions[j]
        pnl = d * (pos.exit_qty_value - pos.qty0 * pos.entry_fill)
        risk = pos.initial_risk
        reason_text = "" if self.s.entry_reason is None else self.s.entry_reason[pos.signal_bar, j]
        ts = self.p.timestamps
        self.trades.append(
            {
                "symbol": self.p.symbols[j],
                "direction": "long" if d == 1 else "short",
                "signal_time": ts[pos.signal_bar],
                "entry_time": ts[pos.entry_bar],
                "entry_open": pos.entry_open,
                "entry_price": pos.entry_fill,
                "exit_time": ts[i],
                "exit_raw": pos.exit_raw_value / pos.qty0,
                "exit_price": pos.exit_qty_value / pos.qty0,
                "qty": pos.qty0,
                "initial_stop": pos.initial_stop,
                "stop": pos.stop,
                "target": pos.target,
                "initial_risk": risk,
                "risk_pct": pos.qty0 * risk / pos.equity_at_entry,
                "notional_pct": pos.qty0 * pos.entry_open / pos.equity_at_entry,
                "pnl": pnl,
                "r_multiple": r_multiple(pnl / pos.qty0, risk),
                "mae_r": d * (pos.worst - pos.entry_open) / risk,
                "mfe_r": d * (pos.best - pos.entry_open) / risk,
                "bars_held": i - pos.entry_bar,
                "equity_at_entry": pos.equity_at_entry,
                "exit_reason": reason,
                "exit_at_open": reason in AT_OPEN_REASONS,
                "partial_exit": pos.partial,
                "entry_reason": reason_text,
                "entry_bar": pos.entry_bar,
                "exit_bar": i,
            }
        )

    def _target_qty(self, pos: _Position) -> float:
        if self.cfg.target_fraction >= 1.0 or pos.partial:
            return pos.qty
        return min(pos.qty, pos.qty0 * self.cfg.target_fraction)

    def _hit_target(self, j: int, i: int, price: float, reason: str) -> None:
        pos = self.positions[j]
        self._exit(j, i, price, self._target_qty(pos), reason)
        if j in self.positions:
            pos.target = math.nan  # one target only; the rest rides the stop
            if pos.stop_after_target == pos.stop_after_target:
                pos.stop = (
                    max(pos.stop, pos.stop_after_target)
                    if pos.direction == 1
                    else min(pos.stop, pos.stop_after_target)
                )

    # --- the bar steps -------------------------------------------------------------------------
    def _at_open(self, j: int, i: int, new_stop: float, exit_now: bool) -> None:
        pos = self.positions[j]
        d, o = pos.direction, self.o[j][i]
        if new_stop == new_stop:  # not NaN; a stop only tightens
            pos.stop = max(pos.stop, new_stop) if d == 1 else min(pos.stop, new_stop)
        if exit_now:
            self._exit(j, i, o, pos.qty, "signal")
        elif (o - pos.stop) * d <= 0:
            self._exit(j, i, o, pos.qty, "stop_gap")
        elif pos.target == pos.target and (o - pos.target) * d >= 0:
            self._hit_target(j, i, o, "target_gap")

    def _enter(self, j: int, i: int, sig: int) -> None:
        cfg, s = self.cfg, self.s
        d = self.ent[j][sig]
        if j in self.positions:
            return self._reject(i, j, d, "position_open")
        if cfg.long_only and d == -1:
            return self._reject(i, j, d, "long_only")
        if self.blocked[i]:
            return self._reject(i, j, d, "fomc")
        o = self.o[j][i]
        stop, target = float(s.stop[sig, j]), float(s.target[sig, j])
        if not (stop == stop and (o - stop) * d > 0):
            return self._reject(i, j, d, "stop_through_open")
        if target == target and (target - o) * d <= 0:
            return self._reject(i, j, d, "target_through_open")
        risk = abs(o - stop)
        if not trade_allowed(risk, 2.0 * self.cost[j]):
            return self._reject(i, j, d, "risk_below_cost")
        equity = self._equity()
        if equity <= 0:
            return self._reject(i, j, d, "no_equity")
        size = float(s.size[sig, j])
        qty = size * equity / o if size == size else cfg.risk_per_trade * equity / risk
        if cfg.max_risk_per_trade is not None:
            qty = min(qty, cfg.max_risk_per_trade * equity / risk)
        used = sum(p.qty * p.mark for p in self.positions.values())
        qty = min(qty, max(cfg.max_exposure * equity - used, 0.0) / o)
        if cfg.whole_shares:
            qty = math.floor(qty)
        if qty <= 0 or qty * o < cfg.min_notional:
            return self._reject(i, j, d, "size")
        fill = o + d * self.cost[j]
        self.cash -= d * qty * fill
        self.positions[j] = _Position(
            sym=j,
            direction=d,
            signal_bar=sig,
            entry_bar=i,
            qty0=qty,
            qty=qty,
            entry_open=o,
            entry_fill=fill,
            initial_stop=stop,
            stop=stop,
            target=target,
            initial_risk=risk,
            equity_at_entry=equity,
            mark=o,
            worst=o,
            best=o,
            stop_after_target=float(s.stop_after_target[sig, j]),
        )

    def _intrabar(self, j: int, i: int) -> None:
        pos = self.positions[j]
        d = pos.direction
        o, hi, lo = self.o[j][i], self.h[j][i], self.lo[j][i]
        adverse, favorable = (lo, hi) if d == 1 else (hi, lo)
        if (adverse - pos.stop) * d <= 0:  # worst case: the stop wins even if the target was hit
            pos.best = max(pos.best, o) if d == 1 else min(pos.best, o)
            self._exit(j, i, pos.stop, pos.qty, "stop")
            return
        if pos.target == pos.target and (favorable - pos.target) * d >= 0:
            pos.worst = min(pos.worst, o) if d == 1 else max(pos.worst, o)
            self._hit_target(j, i, pos.target, "target")
            if j not in self.positions:
                return
        if d == 1:
            pos.worst, pos.best = min(pos.worst, lo), max(pos.best, hi)
        else:
            pos.worst, pos.best = max(pos.worst, hi), min(pos.best, lo)

    def run(self, s0: int, s1: int) -> IntradayResult:
        k = len(self.p.symbols)
        equity = np.empty(s1 - s0 + 1)
        for s in range(s0, s1 + 1):
            b0, b1 = (int(x) for x in self.p.bounds[s])
            last = [int(x) for x in self.p.last_bar[s]]
            pending_entry: list[int] = [-1] * k  # signal bar of the pending entry
            pending_exit = [False] * k
            pending_stop = [math.nan] * k
            for i in range(b0, b1 + 1):
                for j in range(k):
                    c = self.c[j][i]
                    if c != c:  # no bar for this symbol
                        continue
                    if j in self.positions:
                        self._at_open(j, i, pending_stop[j], pending_exit[j])
                    if pending_entry[j] >= 0:
                        self._enter(j, i, pending_entry[j])
                    pending_entry[j], pending_exit[j], pending_stop[j] = -1, False, math.nan
                    if j in self.positions:
                        self._intrabar(j, i)
                    pos = self.positions.get(j)
                    if pos is not None:
                        pos.mark = c
                    if i == last[j]:
                        if pos is not None:
                            self._exit(j, i, c, pos.qty, "eod")
                        continue
                    if pos is not None:
                        pending_exit[j] = self.ext[j][i] or self.ext_dir[pos.direction][j][i]
                        pending_stop[j] = self.trail[pos.direction][j][i]
                    if self.ent[j][i] != 0:
                        pending_entry[j] = i
            equity[s - s0] = self.cash  # flat: every position exited at its last bar
        return IntradayResult(
            equity=pd.Series(equity, index=self.p.sessions[s0 : s1 + 1], name="equity"),
            trades=pd.DataFrame(self.trades, columns=TRADE_COLUMNS),
            rejections=pd.DataFrame(
                self.rejections, columns=["time", "symbol", "direction", "reason"]
            ),
            config=self.cfg,
        )


def run_intraday(
    panel: IntradayPanel,
    signals: IntradaySignals,
    config: IntradayConfig | None = None,
    start=None,
    end=None,
) -> IntradayResult:
    """Simulate the signals on the sessions between the dates start and end (inclusive)."""
    s0, s1 = panel.session_range(start, end)
    return _Simulator(panel, signals, config or IntradayConfig()).run(s0, s1)
