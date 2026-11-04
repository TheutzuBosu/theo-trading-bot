"""Intraday paper trading loop, daily self-learning, and emergency kill switch (Faza B, B6c/B6d).

Orchestrates:
- D1b (VWAP & Ladder #1, Long+Short+Leverage D31) on SPY and QQQ, evaluated on the exact D1b check
  bars (10:11, 10:57, ..., 14:47 ET bar closes), with a short catch-up window for late runs and
  idempotent signal keys stored in `state/live_journal.json`.
- No artificial daily trade count cap: takes every trade passing D1b + AI + Risk Guard.
- Position management in the spirit of the backtest: the stop only tightens (session VWAP trail),
  50% partial exit at the D1b target with the `stop_after_target` rule, time exit at 15:30 ET
  (30 minutes before the session close, also on 13:00 early closes) and EOD flattening.
- Every closed trade is recorded (trades.csv + Romanian post-mortem + meta-label dataset) so the
  daily learner really learns from it.
- Real-time synchronization of `state/` to the `state` branch on GitHub for the Vercel dashboard.
"""

from __future__ import annotations

import logging
import math
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from src.ai.autopsy import build_autopsy_record
from src.ai.daily_learner import compute_hourly_multipliers, retrain_on_daily_trades
from src.ai.meta_label import FEATURE_COLUMNS, compute_feature_frame
from src.ai.veto import check_news_veto, fetch_recent_news
from src.alerts.telegram import (
    send_daily_summary_alert,
    send_entry_alert,
    send_error_alert,
    send_exit_alert,
    send_kill_alert,
)
from src.backtest.intraday_costs import STOCK_HALF_SPREAD
from src.broker.alpaca_paper import (
    AlpacaPaperAdapter,
    exec_symbol_for,
    make_client_order_id,
    resolve_execution_instrument,
    round_price,
)
from src.data.intraday import nyse_sessions
from src.live.state_writer import (
    KILL_SWITCH_FILE,
    fetch_remote_kill_switch,
    sync_state_dir_to_github,
    write_state_files,
)
from src.risk.guard import (
    MAX_DRAWDOWN_KILL_PCT,
    MAX_RISK_PER_TRADE_PCT,
    MAX_TOTAL_EXPOSURE,
    can_move_stop,
    evaluate_order_risk,
    symbol_family,
)
from src.state.store import (
    TRADE_COLUMNS,
    StateStore,
    init_clean_paper_state,
    reconcile_positions,
)
from src.strategies.intraday_d1 import D1bParams, _session_vwap, generate_d1b_signals

logger = logging.getLogger(__name__)
NY_TZ = ZoneInfo("America/New_York")

SIGNAL_SYMBOLS: tuple[str, ...] = ("SPY", "QQQ")
SIGNAL_MAX_AGE_MIN = 10.0  # catch-up window after a D1b check bar closes
BAR_SETTLE_SECONDS = 8.0  # wait after a bar closes so Alpaca has published it
DEFAULT_MAX_WAIT_MIN = 12.0  # a scheduled run waits at most this long for the next D1b event
DEFAULT_META_THRESHOLD = 0.52
MIN_META_SAMPLES = 40
PARTIAL_FRACTION = 0.5  # D1b ladder: 50% at take_profit_0
STRATEGY_NAME = "D1b (VWAP & Ladder #1)"


# --------------------------------------------------------------------------- time helpers
def _now_et(now: datetime | None = None) -> datetime:
    dt = now or datetime.now(UTC)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(NY_TZ)


def session_bounds(now_et: datetime) -> tuple[datetime, datetime] | None:
    """Regular session (open, close) in New York time for the day of `now_et`, or None."""
    day = now_et.date()
    try:
        sched = nyse_sessions(day, day)
    except Exception:  # noqa: BLE001
        return None
    if sched.empty:
        return None
    row = sched.iloc[0]
    return (
        pd.Timestamp(row["open"]).tz_convert(NY_TZ).to_pydatetime(),
        pd.Timestamp(row["close"]).tz_convert(NY_TZ).to_pydatetime(),
    )


def d1b_event_times(
    open_et: datetime, close_et: datetime, params: D1bParams | None = None
) -> dict[str, Any]:
    """Wall-clock times when D1b check bars close, plus the time exit (15:30 / 12:30 ET).

    Mirrors `_select_check_and_exit_bars`: check bars start at open + 41m every 46m while the bar
    start is <= close - 32m; a bar starting at t closes at t + 1m.
    """
    p = params or D1bParams()
    checks: list[datetime] = []
    cutoff = close_et - timedelta(minutes=p.exit_before_close_min + 2)
    t = open_et + timedelta(minutes=p.first_check_min)
    while t <= cutoff:
        checks.append(t + timedelta(minutes=1))
        t += timedelta(minutes=p.check_freq_min)
    return {"checks": checks, "time_exit": close_et - timedelta(minutes=p.exit_before_close_min)}


def _minutes_to_close(ts_et: datetime, close_et: datetime | None = None) -> float:
    close_dt = close_et or ts_et.replace(hour=16, minute=0, second=0, microsecond=0)
    return (close_dt - ts_et).total_seconds() / 60.0


def plan_auto_run(now_et: datetime, max_wait_min: float = DEFAULT_MAX_WAIT_MIN) -> dict[str, Any]:
    """Decide what a scheduled run does now: skip, wait for the next D1b event, or run."""
    bounds = session_bounds(now_et)
    if bounds is None:
        return {"action": "closed", "reason": "Piața SUA este închisă azi.", "sleep_s": 0.0}
    open_et, close_et = bounds
    events = d1b_event_times(open_et, close_et)
    if now_et < open_et - timedelta(minutes=5):
        return {"action": "closed", "reason": "Înainte de deschiderea pieței.", "sleep_s": 0.0}
    if now_et >= events["time_exit"]:
        return {"action": "run", "reason": "După ora de ieșire D1b: închidere + EOD."}
    open_ready = open_et + timedelta(minutes=5)
    upcoming = [e for e in [open_ready, *events["checks"], events["time_exit"]] if e > now_et]
    if upcoming:
        wait_s = (upcoming[0] - now_et).total_seconds()
        if wait_s <= max_wait_min * 60.0:
            return {
                "action": "wait",
                "reason": f"Aștept evenimentul D1b de la {upcoming[0].strftime('%H:%M')} ET.",
                "sleep_s": wait_s + BAR_SETTLE_SECONDS,
                "event": upcoming[0],
            }
    return {"action": "run", "reason": "Pas de administrare (stop-uri) și recuperare semnale."}


# ------------------------------------------------------------------------ small helpers
def _parse_hourly_multipliers(raw: Any) -> dict[int, float]:
    """Accept {"09:00": 0.8}, {"9": 0.8} or {9: 0.8} (EOD writes "HH:00" keys)."""
    out: dict[int, float] = {}
    if not isinstance(raw, dict):
        return out
    for k, v in raw.items():
        try:
            hour = int(str(k).split(":")[0])
            out[hour] = float(v)
        except (TypeError, ValueError):
            continue
    return out


def _finite(x: Any) -> bool:
    try:
        return math.isfinite(float(x))
    except (TypeError, ValueError):
        return False


def _signal_key(symbol: str, ts: pd.Timestamp, direction: str) -> str:
    return f"{symbol.upper()}|{pd.Timestamp(ts).isoformat()}|{direction}"


def find_fresh_d1b_signal(
    bars: pd.DataFrame,
    now_et: datetime,
    max_age_min: float = SIGNAL_MAX_AGE_MIN,
) -> tuple[pd.Timestamp, pd.Series] | None:
    """Latest D1b entry signal of today if its bar closed at most `max_age_min` minutes ago."""
    if bars.empty:
        return None
    sig_df = generate_d1b_signals(bars, D1bParams())
    idx = pd.DatetimeIndex(sig_df.index)
    ny_idx = idx.tz_convert(NY_TZ) if idx.tz is not None else idx.tz_localize(NY_TZ)
    today_mask = np.asarray([d == now_et.date() for d in ny_idx.date])
    entries = sig_df.loc[today_mask & (sig_df["entry"].to_numpy() != 0)]
    if entries.empty:
        return None
    ts = pd.Timestamp(entries.index[-1])
    bar_close = (ts.tz_convert(NY_TZ) if ts.tz is not None else ts.tz_localize(NY_TZ)) + timedelta(
        minutes=1
    )
    age_min = (now_et - bar_close.to_pydatetime()).total_seconds() / 60.0
    if age_min < -0.05 or age_min > max_age_min:
        return None
    return ts, entries.iloc[-1]


def translate_signal_stop(
    *,
    signal_stop: float,
    signal_price: float,
    exec_price: float,
    leverage: int,
    signal_direction: str,
    same_instrument: bool,
) -> float:
    """Map a stop expressed on SPY/QQQ to the traded ETF using current prices (D31/D32)."""
    if same_instrument:
        return round_price(signal_stop)
    if signal_direction == "long":
        dist = (signal_price - signal_stop) / signal_price
    else:
        dist = (signal_stop - signal_price) / signal_price
    return round_price(exec_price * (1.0 - int(leverage) * dist))


def _today_signal_view(bars: pd.DataFrame, now_et: datetime) -> tuple[float, float]:
    """(last close, session VWAP at the last bar) of today's bars; NaN when unavailable."""
    if bars.empty:
        return math.nan, math.nan
    idx = pd.DatetimeIndex(bars.index)
    ny_idx = idx.tz_convert(NY_TZ) if idx.tz is not None else idx.tz_localize(NY_TZ)
    mask = np.asarray([d == now_et.date() for d in ny_idx.date])
    today = bars.loc[mask]
    if today.empty:
        return float(bars["close"].iloc[-1]), math.nan
    day_idx = pd.DatetimeIndex(ny_idx[mask]).tz_localize(None).normalize()
    days = pd.Series(day_idx, index=today.index)
    vwap = _session_vwap(today, days)
    return float(today["close"].iloc[-1]), float(vwap.iloc[-1])


def fit_meta_model_from_dataset(
    store: StateStore, base_threshold: float = DEFAULT_META_THRESHOLD
) -> tuple[Any | None, dict[str, Any]]:
    """Fit the meta-label filter on all closed live trades once there are enough of them."""
    df = store.read_meta_dataset()
    cols = list(FEATURE_COLUMNS)
    if df.empty or len(df) < MIN_META_SAMPLES or not set(cols).issubset(df.columns):
        return None, {"meta_samples": int(len(df)), "meta_active": False}
    y = (pd.to_numeric(df["r_multiple"], errors="coerce").fillna(0.0) > 0.0).astype(int)
    if y.nunique() < 2:
        return None, {"meta_samples": int(len(df)), "meta_active": False}
    X = df.loc[:, cols].apply(pd.to_numeric, errors="coerce").fillna(0.0)
    res = retrain_on_daily_trades(
        X,
        y,
        X.iloc[0:0],
        y.iloc[0:0],
        base_threshold=base_threshold,
    )
    stats = {k: v for k, v in res.items() if k != "pipeline"}
    stats.update({"meta_samples": int(len(df)), "meta_active": True})
    return res["pipeline"], stats


# ---------------------------------------------------------------------- state refresh
def initialize_live_paper_state(
    state_dir: Path,
    adapter: AlpacaPaperAdapter | None = None,
    *,
    initial_capital: float = 500.0,
    as_of_date: str | None = None,
    sync_github: bool = False,
    github_token: str | None = None,
    session: Any | None = None,
    spy_price: float | None = None,
    now_et: datetime | None = None,
) -> dict[str, Any]:
    """Initialize or refresh `state/` from the real Alpaca Paper account (`is_sample: False`)."""
    now = _now_et(now_et)
    date_str = as_of_date or now.strftime("%Y-%m-%d")
    store = StateStore(state_dir)

    if not store.summary_path.exists():
        init_clean_paper_state(
            state_dir,
            initial_capital=initial_capital,
            date_str=date_str,
            updated_at=now.isoformat(),
            overwrite=False,
        )

    summary = store.read_summary()
    equity_df = store.read_equity()
    trades_df = store.read_trades()
    journal = store.read_journal()

    if adapter is not None:
        acct = adapter.get_account_state()
        broker_positions = adapter.get_open_positions()
        equity = float(acct.get("equity", initial_capital))
        init_cap = float(summary.get("initial_capital", initial_capital))
        total_pnl = round(equity - init_cap, 2)
        total_pnl_pct = round((total_pnl / init_cap) * 100.0, 2) if init_cap > 0 else 0.0

        # Daily PnL against the broker's previous-session close equity (source of truth)
        last_eq = float(acct.get("last_equity", 0.0) or 0.0)
        if last_eq <= 0:
            prior = (
                equity_df.loc[equity_df["date"].astype(str) < date_str]
                if not equity_df.empty
                else equity_df
            )
            last_eq = float(prior["bot_equity"].iloc[-1]) if not prior.empty else init_cap
        today_pnl = round(equity - last_eq, 2)
        today_pnl_pct = round((today_pnl / last_eq) * 100.0, 2) if last_eq > 0 else 0.0

        peak_eq = max(
            [init_cap, equity]
            + (equity_df["bot_equity"].astype(float).tolist() if not equity_df.empty else [])
        )
        curr_dd_pct = round(((equity - peak_eq) / peak_eq) * 100.0, 2) if peak_eq > 0 else 0.0
        prev_max_dd = float(summary.get("max_drawdown_pct", 0.0))
        max_dd_pct = round(min(prev_max_dd, curr_dd_pct), 2)

        # SPY buy & hold benchmark from the first observed SPY price
        if spy_price is not None and spy_price > 0 and not summary.get("spy_start_price"):
            summary["spy_start_price"] = round(float(spy_price), 4)
        spy_start = float(summary.get("spy_start_price") or 0.0)
        spy_bh = (
            round(init_cap * float(spy_price) / spy_start, 2)
            if spy_price is not None and spy_price > 0 and spy_start > 0
            else None
        )

        open_trades = journal.get("open_trades", {})
        open_list: list[dict[str, Any]] = []
        for sym, pos in sorted(broker_positions.items()):
            entry_p = float(pos.get("entry_price", 0.0))
            curr_p = float(pos.get("current_price", entry_p))
            unr_pnl = float(pos.get("unrealized_pnl", 0.0))
            tr = open_trades.get(sym, {})
            init_risk = float(tr.get("initial_risk_dollars", 0.0) or 0.0)
            open_list.append(
                {
                    "symbol": sym,
                    "direction": pos.get("direction", "long"),
                    "entry_time": str(tr.get("entry_time", "")),
                    "qty": round(float(pos.get("qty", 0.0)), 4),
                    "entry_price": round(entry_p, 4),
                    "current_price": round(curr_p, 4),
                    "stop": float(tr.get("exec_stop", 0.0) or 0.0),
                    "initial_stop": float(tr.get("exec_initial_stop", 0.0) or 0.0),
                    "unrealized_pnl": round(unr_pnl, 2),
                    "unrealized_r": round(unr_pnl / init_risk, 2) if init_risk > 0 else 0.0,
                    "entry_reason": str(
                        tr.get("entry_reason")
                        or "Poziție necunoscută botului, găsită în contul Alpaca Paper."
                    ),
                }
            )

        summary.update(
            {
                "mode": "PAPER",
                "is_sample": False,
                "initial_capital": round(init_cap, 2),
                "equity": round(equity, 2),
                "total_pnl": total_pnl,
                "total_pnl_pct": total_pnl_pct,
                "today_pnl": today_pnl,
                "today_pnl_pct": today_pnl_pct,
                "current_drawdown_pct": curr_dd_pct,
                "max_drawdown_pct": max_dd_pct,
                "updated_at": now.isoformat(),
                "positions": open_list,
            }
        )
        store.write_positions(open_list)

        last_bh = (
            float(equity_df.iloc[-1]["spy_buy_hold"]) if not equity_df.empty else round(init_cap, 2)
        )
        row = {
            "date": date_str,
            "bot_equity": round(equity, 2),
            "spy_buy_hold": spy_bh if spy_bh is not None else last_bh,
            "daily_pnl": today_pnl,
            "drawdown_pct": curr_dd_pct,
        }
        if not equity_df.empty and str(equity_df.iloc[-1]["date"]) == date_str:
            for key, val in row.items():
                equity_df.loc[equity_df.index[-1], key] = val
        else:
            equity_df = pd.concat([equity_df, pd.DataFrame([row])], ignore_index=True)

    write_state_files(
        state_dir=state_dir,
        summary=summary,
        equity_df=equity_df,
        trades_df=trades_df,
        sync_github=sync_github,
        github_token=github_token,
        session=session,
    )
    return summary


# ------------------------------------------------------------------ entry evaluation
def evaluate_symbol_candidate(
    symbol: str,
    bars: pd.DataFrame,
    *,
    equity: float,
    open_positions: set[str],
    current_exposure: float,
    daily_pnl_pct: float,
    drawdown_pct: float,
    kill_switch_active: bool = False,
    leverage: int = 2,
    shorting_enabled: bool = False,
    etf_prices: dict[str, float] | None = None,
    hourly_multipliers: dict[int, float] | None = None,
    meta_model: Any | None = None,
    meta_threshold: float = DEFAULT_META_THRESHOLD,
    finnhub_key: str | None = None,
    gemini_client: Any | None = None,
    http_session: Any | None = None,
    now_et: datetime | None = None,
    max_signal_age_min: float = SIGNAL_MAX_AGE_MIN,
    processed_signals: set[str] | None = None,
    session_close_et: datetime | None = None,
    max_notional: float | None = None,
) -> dict[str, Any]:
    """Evaluate today's latest fresh D1b check-bar signal on `symbol` through AI + Risk Guard."""
    if bars.empty:
        return {"action": "none", "reason": "Nu există bare intraday disponibile."}
    now = _now_et(now_et)

    found = find_fresh_d1b_signal(bars, now, max_signal_age_min)
    if found is None:
        return {"action": "none", "reason": "Niciun semnal D1b proaspăt (bară de verificare)."}
    sig_ts, sig_row = found
    raw_sig = int(sig_row.get("entry", 0))
    direction = "long" if raw_sig > 0 else "short"
    key = _signal_key(symbol, sig_ts, direction)
    if processed_signals and key in processed_signals:
        return {"action": "none", "reason": "Semnalul acesta a fost deja procesat.", "key": key}

    prices = etf_prices or {}
    last_close = float(bars["close"].iloc[-1])
    signal_price = float(prices.get(symbol) or last_close)
    signal_stop = float(sig_row["stop"])
    signal_target = float(sig_row["target"]) if _finite(sig_row.get("target")) else None
    stop_after_target = (
        float(sig_row["stop_after_target"]) if _finite(sig_row.get("stop_after_target")) else None
    )
    base_reason = str(sig_row.get("entry_reason") or f"D1b ({direction.upper()}) pe {symbol}")
    if (direction == "long" and signal_price <= signal_stop) or (
        direction == "short" and signal_price >= signal_stop
    ):
        return {
            "action": "skip",
            "reason": "Semnal expirat: prețul a trecut deja de stop-ul D1b.",
            "key": key,
        }

    # 1. Meta-labeling (features at the signal bar) + daily learner hourly multiplier
    feats = compute_feature_frame(bars)
    feat_row = feats.loc[sig_ts] if sig_ts in feats.index else feats.iloc[-1]
    features = {c: float(feat_row[c]) if _finite(feat_row[c]) else 0.0 for c in FEATURE_COLUMNS}
    meta_prob = 0.60
    if meta_model is not None:
        X_last = pd.DataFrame([features], columns=list(FEATURE_COLUMNS))
        meta_prob = float(meta_model.predict_proba(X_last)[0, 1])
        if meta_prob < meta_threshold:
            msg = f"Filtru AI meta_label: probabilitate {meta_prob:.2f} < {meta_threshold:.2f}"
            return {"action": "skip", "reason": msg, "key": key}

    sig_et = sig_ts.tz_convert(NY_TZ) if sig_ts.tz is not None else sig_ts.tz_localize(NY_TZ)
    hour_et = int(sig_et.hour)
    hour_mult = float((hourly_multipliers or {}).get(hour_et, 1.0))
    if hour_mult <= 0.0:
        return {
            "action": "skip",
            "reason": f"Filtru învățare zilnică: ora {hour_et}:00 ET dezactivată.",
            "key": key,
        }

    # 2. News veto (Finnhub + Gemini / deterministic crisis keywords). None -> key from settings.
    news_items = fetch_recent_news(symbol, finnhub_key=finnhub_key, session=http_session)
    headlines = [item["headline"] for item in news_items if item.get("headline")]
    allow_news, news_reason = check_news_veto(symbol, direction, headlines, client=gemini_client)
    if not allow_news:
        return {"action": "skip", "reason": f"Veto știri: {news_reason}", "key": key}

    # 3. Map signal to execution instrument (D31) using that instrument's own price (D32)
    raw_dist = abs(signal_price - signal_stop)
    risk_budget = equity * MAX_RISK_PER_TRADE_PCT * min(hour_mult, 1.0)
    raw_qty = max(0.01, risk_budget / raw_dist)
    exec_sym = exec_symbol_for(symbol, direction, leverage, equity, shorting_enabled)
    exec_px = signal_price if exec_sym == symbol.upper() else prices.get(exec_sym)
    if exec_px is None or not _finite(exec_px) or float(exec_px) <= 0:
        return {
            "action": "skip",
            "reason": f"Preț curent indisponibil pentru {exec_sym}; nu calculez ordinul.",
            "key": key,
        }
    exec_spec = resolve_execution_instrument(
        symbol=symbol,
        direction=direction,
        qty=raw_qty,
        entry_price=signal_price,
        stop_price=signal_stop,
        target_price=signal_target,
        leverage=leverage,
        account_equity=equity,
        shorting_enabled=shorting_enabled,
        instrument_price=float(exec_px),
    )
    exec_dir = "long" if exec_spec["side"] == "buy" else "short"
    exec_price = float(exec_spec["entry_price"])
    exec_stop = float(exec_spec["stop_price"])
    stop_dist = abs(exec_price - exec_stop)
    if stop_dist <= 0:
        return {"action": "skip", "reason": "Distanță stop-loss invalidă (0).", "key": key}

    # 4. Position sizing capped by risk per trade (0.5% * hour_mult) and remaining exposure
    qty_by_risk = risk_budget / stop_dist
    remaining_notional = max(0.0, equity * MAX_TOTAL_EXPOSURE - current_exposure)
    qty_by_notional = (remaining_notional * 0.98) / exec_price if exec_price > 0 else 0.0
    if max_notional is not None:  # broker buying power left (cash-like 500 $ account)
        qty_by_notional = min(qty_by_notional, max(0.0, max_notional) / exec_price)
    qty = round(min(float(exec_spec["qty"]), qty_by_risk, qty_by_notional), 4)
    if qty <= 0.0:
        return {"action": "skip", "reason": "Cantitate calculată 0 (expunere plină).", "key": key}

    risk_dollars = qty * stop_dist
    typ_spread = STOCK_HALF_SPREAD * 2.0
    allowed, risk_reason = evaluate_order_risk(
        symbol=exec_sym,
        direction=exec_dir,
        entry_price=exec_price,
        stop=exec_stop,
        qty=qty,
        equity=equity,
        current_exposure=current_exposure,
        open_positions=open_positions,
        daily_pnl_pct=daily_pnl_pct,
        drawdown_pct=drawdown_pct,
        timestamp=pd.Timestamp(now),
        minutes_to_close=_minutes_to_close(now, session_close_et),
        current_spread=typ_spread,
        typical_spread=typ_spread,
        kill_switch_active=kill_switch_active,
    )
    if not allowed:
        return {"action": "skip", "reason": risk_reason, "key": key}

    exec_note = (
        f"D31: {symbol} {direction.upper()} -> BUY {exec_sym} ({exec_spec['leverage']}x)"
        if exec_dir == "long"
        else f"D31: SELL SHORT {exec_sym}"
    )
    full_reason = f"{base_reason} · {exec_note} · AI p={meta_prob:.2f} · mult_oră={hour_mult:.2f}"
    return {
        "action": "enter",
        "key": key,
        "signal_symbol": symbol.upper(),
        "exec_symbol": exec_sym,
        "signal_direction": direction,
        "exec_direction": exec_dir,
        "side": exec_spec["side"],
        "qty": qty,
        "entry_price": exec_price,
        "stop_price": exec_stop,
        "target_price": exec_spec["target_price"],
        "risk_dollars": risk_dollars,
        "risk_pct": risk_dollars / equity if equity > 0 else 0.0,
        "leverage": int(exec_spec["leverage"]),
        "timestamp": sig_et.strftime("%Y%m%dT%H%M"),
        "signal_time": sig_et.isoformat(),
        "signal_price": signal_price,
        "signal_stop": signal_stop,
        "signal_target": signal_target,
        "signal_stop_after_target": stop_after_target,
        "features": features,
        "meta_prob": meta_prob,
        "reason": full_reason,
    }


def evaluate_mover_candidate(
    opp: dict[str, Any],
    *,
    equity: float,
    open_positions: set[str],
    current_exposure: float,
    daily_pnl_pct: float,
    drawdown_pct: float,
    kill_switch_active: bool = False,
    shorting_enabled: bool = False,
    prices: dict[str, float] | None = None,
    now_et: datetime | None = None,
    processed_signals: set[str] | None = None,
    session_close_et: datetime | None = None,
    max_notional: float | None = None,
) -> dict[str, Any]:
    """Evaluate a discovered individual stock opportunity (D33) through sizing and Risk Guard."""
    sym = str(opp.get("symbol", "")).upper().strip()
    direction = str(opp.get("direction", "long")).lower().strip()
    if not sym or opp.get("action") != "enter" or direction not in ("long", "short"):
        return {"action": "none", "reason": "Oportunitate inactivă sau direcție invalidă."}

    now = _now_et(now_et)
    key = f"MOVER|{sym}|{now.strftime('%Y-%m-%d')}|{direction}"
    if processed_signals and key in processed_signals:
        return {
            "action": "none",
            "reason": "Oportunitatea pe această acțiune a fost deja executată azi.",
            "key": key,
        }

    px_map = prices or {}
    opp_price = float(opp.get("price") or 0.0)
    signal_price = float(px_map.get(sym) or opp_price)
    if not _finite(signal_price) or signal_price <= 0:
        return {"action": "skip", "reason": f"Preț curent indisponibil pentru {sym}.", "key": key}

    opp_stop = float(opp.get("stop_price") or 0.0)
    raw_dist_pct = (
        abs(opp_price - opp_stop) / opp_price if opp_price > 0 and opp_stop > 0 else 0.015
    )
    raw_dist_pct = min(0.04, max(0.006, raw_dist_pct))
    rr_ratio = min(12.0, max(3.0, float(opp.get("rr_ratio") or 4.0)))
    stake_dollars = min(35.0, max(5.0, float(opp.get("stake_dollars") or 12.0)))

    if direction == "long":
        signal_stop = round_price(signal_price * (1.0 - raw_dist_pct))
        signal_target = round_price(signal_price * (1.0 + raw_dist_pct * rr_ratio))
        stop_after_target = round_price(signal_price * (1.0 + raw_dist_pct * 0.5))
    else:
        signal_stop = round_price(signal_price * (1.0 + raw_dist_pct))
        signal_target = round_price(signal_price * (1.0 - raw_dist_pct * rr_ratio))
        stop_after_target = round_price(signal_price * (1.0 - raw_dist_pct * 0.5))

    exec_sym = exec_symbol_for(
        sym, direction, leverage=1, account_equity=equity, shorting_enabled=shorting_enabled
    )
    exec_px = signal_price if exec_sym == sym else px_map.get(exec_sym)
    if exec_px is None or not _finite(exec_px) or float(exec_px) <= 0:
        return {
            "action": "skip",
            "reason": f"Preț curent indisponibil pentru instrumentul de execuție {exec_sym}.",
            "key": key,
        }

    risk_budget = equity * MAX_RISK_PER_TRADE_PCT
    raw_dist = max(abs(signal_price - signal_stop), 1e-4)
    raw_qty = max(0.001, min(stake_dollars / signal_price, risk_budget / raw_dist))
    exec_spec = resolve_execution_instrument(
        symbol=sym,
        direction=direction,
        qty=raw_qty,
        entry_price=signal_price,
        stop_price=signal_stop,
        target_price=signal_target,
        leverage=1,
        account_equity=equity,
        shorting_enabled=shorting_enabled,
        instrument_price=float(exec_px),
    )
    exec_dir = "long" if exec_spec["side"] == "buy" else "short"
    exec_price = float(exec_spec["entry_price"])
    exec_stop = float(exec_spec["stop_price"])
    stop_dist = abs(exec_price - exec_stop)
    if stop_dist <= 0:
        return {"action": "skip", "reason": "Distanță stop-loss invalidă (0).", "key": key}

    qty_by_stake = stake_dollars / exec_price if exec_price > 0 else 0.0
    qty_by_risk = risk_budget / stop_dist
    remaining_notional = max(0.0, equity * MAX_TOTAL_EXPOSURE - current_exposure)
    qty_by_notional = (remaining_notional * 0.98) / exec_price if exec_price > 0 else 0.0
    if max_notional is not None:
        qty_by_notional = min(qty_by_notional, max(0.0, max_notional) / exec_price)
    qty = round(min(float(exec_spec["qty"]), qty_by_stake, qty_by_risk, qty_by_notional), 4)
    if qty <= 0.0 or qty * exec_price < 1.0:
        return {"action": "skip", "reason": "Cantitate sub minimul de 1$ Alpaca.", "key": key}

    risk_dollars = qty * stop_dist
    typ_spread = STOCK_HALF_SPREAD * 2.0
    allowed, risk_reason = evaluate_order_risk(
        symbol=exec_sym,
        direction=exec_dir,
        entry_price=exec_price,
        stop=exec_stop,
        qty=qty,
        equity=equity,
        current_exposure=current_exposure,
        open_positions=open_positions,
        daily_pnl_pct=daily_pnl_pct,
        drawdown_pct=drawdown_pct,
        timestamp=pd.Timestamp(now),
        minutes_to_close=_minutes_to_close(now, session_close_et),
        current_spread=typ_spread,
        typical_spread=typ_spread,
        kill_switch_active=kill_switch_active,
    )
    if not allowed:
        return {"action": "skip", "reason": risk_reason, "key": key}

    notional_dollars = round(qty * exec_price, 2)
    base_reason = str(
        opp.get("reason_ro") or f"Acțiune în mișcare {sym} ({opp.get('change_pct', 0):+.2f}%)"
    )
    exec_note = (
        f"D33 Scanner: {sym} {direction.upper()} -> BUY {exec_sym} "
        f"(miză ~{notional_dollars:.2f}$, R:R 1:{rr_ratio:.1f})"
        if exec_dir == "long"
        else (
            f"D33 Scanner: SELL SHORT {exec_sym} "
            f"(miză ~{notional_dollars:.2f}$, R:R 1:{rr_ratio:.1f})"
        )
    )
    return {
        "action": "enter",
        "key": key,
        "signal_symbol": sym,
        "exec_symbol": exec_sym,
        "signal_direction": direction,
        "exec_direction": exec_dir,
        "side": exec_spec["side"],
        "qty": qty,
        "entry_price": exec_price,
        "stop_price": exec_stop,
        "target_price": exec_spec["target_price"],
        "risk_dollars": risk_dollars,
        "risk_pct": risk_dollars / equity if equity > 0 else 0.0,
        "leverage": int(exec_spec["leverage"]),
        "timestamp": now.strftime("%Y%m%dT%H%M"),
        "signal_time": now.isoformat(),
        "signal_price": signal_price,
        "signal_stop": signal_stop,
        "signal_target": signal_target,
        "signal_stop_after_target": stop_after_target,
        "features": {},
        "meta_prob": float(opp.get("confidence") or 0.7),
        "reason": f"{base_reason} · {exec_note}",
    }


# --------------------------------------------------------------- closed trade recording
def _finalize_trade(
    store: StateStore,
    trade: dict[str, Any],
    *,
    gemini_client: Any | None,
    send_alerts: bool,
    http_session: Any | None,
) -> str:
    """Autopsy + lesson, append to trades.csv, Telegram exit alert. Returns the lesson."""
    rec = build_autopsy_record(trade, client=gemini_client)
    store.append_autopsy(rec)
    lesson = str(rec["lesson"])
    row = {col: trade.get(col, "") for col in TRADE_COLUMNS}
    row["entry_reason"] = f"{trade.get('entry_reason', 'D1b intraday')} | Lecție: {lesson}"
    trades_df = store.read_trades()
    trades_df = pd.concat([trades_df, pd.DataFrame([row])], ignore_index=True)
    store.write_trades(trades_df)
    if send_alerts:
        send_exit_alert(
            symbol=str(trade.get("symbol", "SPY")),
            direction=str(trade.get("direction", "long")),
            pnl=float(trade.get("pnl", 0.0) or 0.0),
            r_multiple=float(trade.get("r_multiple", 0.0) or 0.0),
            exit_reason=str(trade.get("exit_reason", "eod")),
            exit_price=float(trade.get("exit_price", 0.0) or 0.0),
            lesson=lesson,
            mode="PAPER",
            session=http_session,
        )
    return lesson


def _excursions_r(
    tr: dict[str, Any], bars: pd.DataFrame | None, exit_time: datetime
) -> tuple[float, float]:
    """(MAE, MFE) in R on the signal symbol between entry and exit (0, 0 when unknown)."""
    if bars is None or bars.empty:
        return 0.0, 0.0
    try:
        p0 = float(tr["signal_entry_price"])
        r_sig = abs(p0 - float(tr["signal_initial_stop"]))
        start = pd.Timestamp(tr["entry_time"])
        end = pd.Timestamp(exit_time)
        idx = pd.DatetimeIndex(bars.index)
        window = bars.loc[(idx >= start) & (idx <= end)]
    except (KeyError, TypeError, ValueError):
        return 0.0, 0.0
    if window.empty or r_sig <= 0:
        return 0.0, 0.0
    hi, lo = float(window["high"].max()), float(window["low"].min())
    if tr.get("signal_direction") == "short":
        return round((p0 - hi) / r_sig, 3), round((p0 - lo) / r_sig, 3)
    return round((lo - p0) / r_sig, 3), round((hi - p0) / r_sig, 3)


def record_closed_trades(
    store: StateStore,
    adapter: AlpacaPaperAdapter,
    journal: dict[str, Any],
    broker_positions: dict[str, dict[str, Any]],
    *,
    bars_by_symbol: dict[str, pd.DataFrame] | None = None,
    now_et: datetime | None = None,
    gemini_client: Any | None = None,
    send_alerts: bool = True,
    http_session: Any | None = None,
    fill_wait_s: float = 10.0,
) -> list[dict[str, Any]]:
    """Record every journal trade that is no longer open at the broker (stop, time, EOD, KILL)."""
    now = _now_et(now_et)
    recorded: list[dict[str, Any]] = []
    open_trades: dict[str, Any] = journal.setdefault("open_trades", {})
    for exec_sym in sorted(list(open_trades)):
        if exec_sym in broker_positions:
            continue
        tr = open_trades[exec_sym]
        entry_dt = pd.Timestamp(tr["entry_time"]).to_pydatetime()
        qty0 = float(tr.get("qty0", tr.get("qty", 0.0)))
        sells: list[dict[str, Any]] = []
        waited = 0.0
        while True:
            fills = adapter.get_filled_orders(entry_dt - timedelta(seconds=5), [exec_sym])
            sells = [
                f
                for f in fills
                if str(f["side"]).lower().endswith("sell")
                and f["client_order_id"] != tr.get("trade_id")
            ]
            sold = sum(f["filled_qty"] for f in sells)
            if sold >= qty0 * 0.999 or waited >= fill_wait_s:
                break
            adapter._sleep(adapter.poll_interval_s)
            waited += adapter.poll_interval_s
        sold = sum(f["filled_qty"] for f in sells)
        proceeds = sum(f["filled_qty"] * f["filled_avg_price"] for f in sells)
        last_px = float(tr.get("last_price", tr["entry_price"]))
        if sold < qty0 * 0.999:  # fills not visible yet: value the rest at the last known price
            proceeds += (qty0 - sold) * last_px
        exit_price = proceeds / qty0 if qty0 > 0 else last_px
        entry_price = float(tr["entry_price"])
        pnl = proceeds - qty0 * entry_price
        init_risk = float(tr.get("initial_risk_dollars", 0.0) or 0.0)
        r_mult = pnl / init_risk if init_risk > 0 else 0.0
        stop_hit = any(str(f["client_order_id"]).endswith("-SL") for f in sells)
        reason = tr.get("exit_reason_pending") or ("stop" if stop_hit else "broker")
        exit_time = (
            pd.Timestamp(sells[-1]["filled_at"]).tz_convert(NY_TZ).to_pydatetime()
            if sells and sells[-1]["filled_at"]
            else now
        )
        mae_r, mfe_r = _excursions_r(tr, (bars_by_symbol or {}).get(tr["signal_symbol"]), exit_time)
        eq0 = float(tr.get("equity_at_entry", 0.0) or 0.0)
        trade = {
            "symbol": exec_sym,
            "direction": tr.get("exec_direction", "long"),
            "signal_time": tr.get("signal_time", ""),
            "entry_time": tr["entry_time"],
            "entry_open": entry_price,
            "entry_price": entry_price,
            "exit_time": exit_time.isoformat(),
            "exit_raw": round(exit_price, 4),
            "exit_price": round(exit_price, 4),
            "qty": qty0,
            "initial_stop": tr.get("exec_initial_stop", ""),
            "stop": tr.get("exec_stop", ""),
            "target": tr.get("exec_target", ""),
            "initial_risk": round(entry_price - float(tr.get("exec_initial_stop", entry_price)), 4),
            "risk_pct": round(init_risk / eq0, 5) if eq0 > 0 else "",
            "notional_pct": round(qty0 * entry_price / eq0, 4) if eq0 > 0 else "",
            "pnl": round(pnl, 2),
            "r_multiple": round(r_mult, 3),
            "mae_r": mae_r,
            "mfe_r": mfe_r,
            "bars_held": int(max(0.0, (exit_time - entry_dt).total_seconds()) // 60),
            "equity_at_entry": eq0,
            "exit_reason": reason,
            "exit_at_open": False,
            "partial_exit": bool(tr.get("partial_done", False)),
            "entry_reason": tr.get("entry_reason", ""),
            "entry_bar": "",
            "exit_bar": "",
        }
        trade["lesson"] = _finalize_trade(
            store,
            trade,
            gemini_client=gemini_client,
            send_alerts=send_alerts,
            http_session=http_session,
        )
        feats = tr.get("features") or {}
        if feats:
            store.append_meta_row(
                {
                    "signal_time": tr.get("signal_time", ""),
                    "symbol": tr.get("signal_symbol", ""),
                    **{c: float(feats.get(c, 0.0)) for c in FEATURE_COLUMNS},
                    "r_multiple": round(r_mult, 4),
                    "target": int(r_mult > 0),
                }
            )
        recorded.append(trade)
        del open_trades[exec_sym]
    return recorded


# ----------------------------------------------------------------- position management
def manage_open_positions(
    adapter: AlpacaPaperAdapter,
    journal: dict[str, Any],
    broker_positions: dict[str, dict[str, Any]],
    bars_by_symbol: dict[str, pd.DataFrame],
    prices: dict[str, float],
    *,
    now_et: datetime,
    time_exit_et: datetime | None,
) -> list[dict[str, Any]]:
    """Apply the D1b exits live: time exit, stop breach, 50% partial at target, VWAP trail."""
    actions: list[dict[str, Any]] = []
    open_trades: dict[str, Any] = journal.setdefault("open_trades", {})
    stamp = now_et.strftime("%H%M%S")

    if time_exit_et is not None and now_et >= time_exit_et:
        if broker_positions:
            adapter.liquidate_all()
            for sym in broker_positions:
                if sym in open_trades:
                    open_trades[sym]["exit_reason_pending"] = "time"
                actions.append({"symbol": sym, "action": "close", "reason": "time"})
        return actions

    for exec_sym, tr in list(open_trades.items()):
        pos = broker_positions.get(exec_sym)
        if pos is None:
            continue
        sig_sym = tr["signal_symbol"]
        sd = tr["signal_direction"]
        bars = bars_by_symbol.get(sig_sym, pd.DataFrame())
        last_close, vwap = _today_signal_view(bars, now_et)
        fallback_sig = float(pos.get("current_price") or 0.0) if exec_sym == sig_sym else math.nan
        p_sig = float(prices.get(sig_sym) or (last_close if _finite(last_close) else fallback_sig))
        q_exec = float(prices.get(exec_sym) or pos.get("current_price") or 0.0)
        if not (_finite(p_sig) and p_sig > 0 and q_exec > 0):
            continue
        tr["last_price"] = q_exec
        tr["qty"] = float(pos.get("qty", tr.get("qty", 0.0)))
        same = exec_sym == sig_sym
        lev = int(tr.get("leverage", 1))
        s_cur = float(tr["signal_stop"])
        is_long = sd == "long"

        # a) signal-level stop breached between runs (the broker stop may lag after translation)
        if (is_long and p_sig <= s_cur) or (not is_long and p_sig >= s_cur):
            adapter.close_position(exec_sym)
            tr["exit_reason_pending"] = "stop"
            actions.append({"symbol": exec_sym, "action": "close", "reason": "stop"})
            continue

        # b) 50% partial take-profit at the D1b target, then the stop_after_target rule
        tgt = tr.get("signal_target")
        if (
            not tr.get("partial_done")
            and tgt is not None
            and _finite(tgt)
            and ((is_long and p_sig >= float(tgt)) or (not is_long and p_sig <= float(tgt)))
            and tr.get("exec_direction", "long") == "long"
        ):
            sat = tr.get("signal_stop_after_target")
            if sat is not None and _finite(sat):
                s_cur = max(s_cur, float(sat)) if is_long else min(s_cur, float(sat))
            new_exec = translate_signal_stop(
                signal_stop=s_cur,
                signal_price=p_sig,
                exec_price=q_exec,
                leverage=lev,
                signal_direction=sd,
                same_instrument=same,
            )
            qty_now = float(pos.get("qty", 0.0))
            sell_qty = round(min(qty_now, float(tr["qty0"]) * PARTIAL_FRACTION), 6)
            if new_exec >= q_exec or sell_qty <= 0 or qty_now - sell_qty <= 1e-6:
                adapter.close_position(exec_sym)
                tr["exit_reason_pending"] = "target"
                actions.append({"symbol": exec_sym, "action": "close", "reason": "target"})
                continue
            res = adapter.sell_partial(
                symbol=exec_sym,
                qty_to_sell=sell_qty,
                remaining_qty=qty_now - sell_qty,
                new_stop=new_exec,
                client_order_id=f"{tr['trade_id']}-TP",
            )
            if res.get("status") == "closed_stop_failed":
                tr["exit_reason_pending"] = "target"
                actions.append({"symbol": exec_sym, "action": "close", "reason": "target"})
                continue
            if res.get("filled_qty", 0.0) > 0:
                tr["partial_done"] = True
            tr["signal_stop"] = s_cur
            tr["exec_stop"] = new_exec
            tr["stop_order_id"] = res.get("stop_order_id", tr.get("stop_order_id", ""))
            tr["stop_seq"] = int(tr.get("stop_seq", 0)) + 1
            actions.append({"symbol": exec_sym, "action": "partial", "result": res})
            continue

        # c) trail the stop to the session VWAP (a stop only tightens)
        if _finite(vwap):
            s_new = max(s_cur, vwap) if is_long else min(s_cur, vwap)
            if s_new != s_cur:
                new_exec = translate_signal_stop(
                    signal_stop=s_new,
                    signal_price=p_sig,
                    exec_price=q_exec,
                    leverage=lev,
                    signal_direction=sd,
                    same_instrument=same,
                )
                cur_exec = float(tr.get("exec_stop", 0.0) or 0.0)
                exec_side = tr.get("exec_direction", "long")
                if (exec_side == "long" and new_exec >= q_exec) or (
                    exec_side == "short" and new_exec <= q_exec
                ):
                    adapter.close_position(exec_sym)
                    tr["exit_reason_pending"] = "stop"
                    actions.append({"symbol": exec_sym, "action": "close", "reason": "stop"})
                    continue
                tr["signal_stop"] = s_new
                if cur_exec > 0 and can_move_stop(cur_exec, new_exec, exec_side):
                    seq = int(tr.get("stop_seq", 0)) + 1
                    res = adapter.replace_stop(
                        symbol=exec_sym,
                        stop_order_id=str(tr.get("stop_order_id", "")),
                        qty=float(pos.get("qty", 0.0)),
                        new_stop=new_exec,
                        client_order_id=f"{tr['trade_id']}-T{seq}{stamp}-SL",
                        side="sell" if exec_side == "long" else "buy",
                    )
                    if res.get("status") in ("closed_stop_failed", "error"):
                        tr["exit_reason_pending"] = "stop"
                        actions.append({"symbol": exec_sym, "action": "close", "reason": "stop"})
                        continue
                    tr["exec_stop"] = new_exec
                    tr["stop_order_id"] = res.get("stop_order_id", tr.get("stop_order_id", ""))
                    tr["stop_seq"] = seq
                    actions.append({"symbol": exec_sym, "action": "trail", "new_stop": new_exec})
    return actions


def _wait_for_closed(
    adapter: AlpacaPaperAdapter, symbols: set[str], timeout_s: float = 15.0
) -> dict[str, dict[str, Any]]:
    """Poll until the given symbols disappear from broker positions (market closes are async)."""
    waited = 0.0
    positions = adapter.get_open_positions()
    while symbols & set(positions) and waited < timeout_s:
        adapter._sleep(adapter.poll_interval_s)
        waited += adapter.poll_interval_s
        positions = adapter.get_open_positions()
    return positions


# --------------------------------------------------------------------------- main step
def run_trading_step(
    *,
    state_dir: Path,
    adapter: AlpacaPaperAdapter,
    bars_by_symbol: dict[str, pd.DataFrame],
    leverage: int = 2,
    meta_model: Any | None = None,
    finnhub_key: str | None = None,
    gemini_client: Any | None = None,
    http_session: Any | None = None,
    sync_github: bool = False,
    github_token: str | None = None,
    send_alerts: bool = True,
    prices: dict[str, float] | None = None,
    now_et: datetime | None = None,
    max_signal_age_min: float = SIGNAL_MAX_AGE_MIN,
    stock_opportunities: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Run one intraday cycle: record closed trades, manage open ones, then take new entries."""
    now = _now_et(now_et)
    prices = dict(prices or {})
    store = StateStore(state_dir)
    if not store.summary_path.exists():
        initialize_live_paper_state(
            state_dir,
            adapter=adapter,
            sync_github=False,
            session=http_session,
            now_et=now,
        )
    journal = store.read_journal()

    acct = adapter.get_account_state()
    broker_positions = adapter.get_open_positions()
    closed_now = record_closed_trades(
        store,
        adapter,
        journal,
        broker_positions,
        bars_by_symbol=bars_by_symbol,
        now_et=now,
        gemini_client=gemini_client,
        send_alerts=send_alerts,
        http_session=http_session,
    )

    def _finish(status: str, extra: dict[str, Any]) -> dict[str, Any]:
        store.write_journal(journal)
        summ = initialize_live_paper_state(
            state_dir,
            adapter=adapter,
            sync_github=sync_github,
            github_token=github_token,
            session=http_session,
            spy_price=prices.get("SPY"),
            now_et=now,
        )
        return {"status": status, "equity": summ.get("equity"), "closed": closed_now, **extra}

    kill_state = store.read_kill_switch()
    if kill_state.get("active"):
        if broker_positions:
            adapter.liquidate_all()
            for sym in broker_positions:
                if sym in journal.get("open_trades", {}):
                    journal["open_trades"][sym]["exit_reason_pending"] = "kill"
            remaining = _wait_for_closed(adapter, set(broker_positions))
            closed_now += record_closed_trades(
                store,
                adapter,
                journal,
                remaining,
                bars_by_symbol=bars_by_symbol,
                now_et=now,
                gemini_client=gemini_client,
                send_alerts=send_alerts,
                http_session=http_session,
            )
        return _finish("halted", {"reason": "KILL switch este activ.", "orders": []})

    recon = reconcile_positions(store.read_positions(), broker_positions)
    store.write_positions(recon["synced_positions"])

    summary = store.read_summary()
    equity = float(acct.get("equity", summary.get("equity", 500.0)))
    init_cap = float(summary.get("initial_capital", 500.0))
    last_eq = float(acct.get("last_equity", 0.0) or 0.0) or equity
    daily_pnl_pct = (equity - last_eq) / last_eq if last_eq > 0 else 0.0

    equity_df = store.read_equity()
    peak_eq = max(
        [init_cap, equity]
        + (equity_df["bot_equity"].astype(float).tolist() if not equity_df.empty else [])
    )
    drawdown_pct = (equity - peak_eq) / peak_eq if peak_eq > 0 else 0.0
    if drawdown_pct <= MAX_DRAWDOWN_KILL_PCT:
        store.write_journal(journal)
        run_kill_switch(
            state_dir=state_dir,
            adapter=adapter,
            reason=f"Drawdown maxim atins ({drawdown_pct * 100:.2f}% <= -15%)",
            sync_github=sync_github,
            github_token=github_token,
            send_alerts=send_alerts,
            http_session=http_session,
            bars_by_symbol=bars_by_symbol,
            now_et=now,
        )
        return {"status": "killed", "reason": "Drawdown maxim atins (-15%)", "orders": []}

    bounds = session_bounds(now)
    time_exit = d1b_event_times(*bounds)["time_exit"] if bounds else None
    close_et = bounds[1] if bounds else None

    # 1. Manage open positions (exits first, so freed capital/families can be reused)
    mgmt = manage_open_positions(
        adapter,
        journal,
        broker_positions,
        bars_by_symbol,
        prices,
        now_et=now,
        time_exit_et=time_exit,
    )
    closed_syms = {a["symbol"] for a in mgmt if a.get("action") == "close"}
    if closed_syms:
        broker_positions = _wait_for_closed(adapter, closed_syms)
        closed_now += record_closed_trades(
            store,
            adapter,
            journal,
            broker_positions,
            bars_by_symbol=bars_by_symbol,
            now_et=now,
            gemini_client=gemini_client,
            send_alerts=send_alerts,
            http_session=http_session,
        )

    orders_submitted: list[dict[str, Any]] = []
    decisions: dict[str, Any] = {}
    if bounds is None or time_exit is None or now >= time_exit or now < bounds[0]:
        return _finish("ok", {"orders": [], "decisions": decisions, "management": mgmt})

    # 2. New entries on fresh D1b check-bar signals
    learning_stats = store.read_learning_stats()
    hourly_multipliers = _parse_hourly_multipliers(learning_stats.get("hourly_multipliers"))
    meta_threshold = float(learning_stats.get("meta_threshold", DEFAULT_META_THRESHOLD))
    if meta_model is None:
        meta_model, _ = fit_meta_model_from_dataset(store, base_threshold=meta_threshold)

    open_syms = set(broker_positions.keys())
    current_exposure = sum(
        abs(float(p.get("market_value", float(p.get("qty", 0)) * float(p.get("current_price", 0)))))
        for p in broker_positions.values()
    )
    processed = set(journal.get("processed_signals", []))
    remote_kill_checked = False
    bp_left = float(acct.get("buying_power", equity) or 0.0) * 0.97

    def _execute_candidate(sym_label: str, cand: dict[str, Any]) -> bool:
        nonlocal remote_kill_checked, current_exposure, bp_left
        decisions[sym_label] = cand
        if cand.get("action") != "enter":
            return True

        # A KILL pressed in the dashboard while this run was waiting must win (race guard)
        if sync_github and not remote_kill_checked:
            remote_kill_checked = True
            if fetch_remote_kill_switch(token=github_token, session=http_session) is True:
                store.set_kill_switch(True, "KILL activat din dashboard", now.isoformat())
                decisions[sym_label] = {"action": "skip", "reason": "KILL activat între timp."}
                return False

        processed.add(cand["key"])
        journal["processed_signals"] = sorted(processed)
        store.write_journal(journal)  # a crash after submitting can never re-enter this signal
        cid = make_client_order_id(cand["exec_symbol"], cand["timestamp"], cand["signal_direction"])
        order_res = adapter.submit_entry_with_stop(
            symbol=cand["exec_symbol"],
            qty=cand["qty"],
            stop_price=cand["stop_price"],
            client_order_id=cid,
            side=cand["side"],
        )
        orders_submitted.append({**order_res, "exec_symbol": cand["exec_symbol"]})
        status = order_res.get("status")
        if status != "filled":
            if send_alerts and status not in ("duplicate_skipped",):
                send_error_alert(
                    component="Execuție ordin Alpaca",
                    error=(
                        f"Ordinul pe {cand['exec_symbol']} nu a fost deschis normal "
                        f"({status}): {order_res.get('error', '')}"
                    ),
                    mode="PAPER",
                    session=http_session,
                )
            return True

        fill_px = float(order_res["filled_avg_price"])
        fill_qty = float(order_res["qty"])
        exec_stop = float(order_res["stop_price"])
        journal.setdefault("open_trades", {})[cand["exec_symbol"]] = {
            "trade_id": cid,
            "signal_symbol": cand["signal_symbol"],
            "signal_direction": cand["signal_direction"],
            "exec_symbol": cand["exec_symbol"],
            "exec_direction": cand["exec_direction"],
            "leverage": cand["leverage"],
            "signal_time": cand["signal_time"],
            "entry_time": now.isoformat(),
            "entry_price": fill_px,
            "qty": fill_qty,
            "qty0": fill_qty,
            "signal_entry_price": cand["signal_price"],
            "signal_stop": cand["signal_stop"],
            "signal_initial_stop": cand["signal_stop"],
            "signal_target": cand["signal_target"],
            "signal_stop_after_target": cand["signal_stop_after_target"],
            "exec_stop": exec_stop,
            "exec_initial_stop": exec_stop,
            "exec_target": cand["target_price"],
            "stop_order_id": order_res.get("stop_order_id", ""),
            "stop_seq": 0,
            "initial_risk_dollars": round(fill_qty * abs(fill_px - exec_stop), 4),
            "equity_at_entry": equity,
            "partial_done": False,
            "last_price": fill_px,
            "entry_reason": cand["reason"],
            "features": cand["features"],
        }
        open_syms.add(cand["exec_symbol"])
        open_syms.add(symbol_family(cand["exec_symbol"]))
        current_exposure += fill_qty * fill_px
        bp_left -= fill_qty * fill_px

        if send_alerts:
            send_entry_alert(
                symbol=cand["exec_symbol"],
                direction=cand["exec_direction"],
                qty=fill_qty,
                entry_price=fill_px,
                stop=exec_stop,
                risk_pct=(fill_qty * abs(fill_px - exec_stop)) / equity if equity > 0 else 0.0,
                reason=cand["reason"],
                strategy=STRATEGY_NAME,
                mode="PAPER",
                session=http_session,
            )
        return True

    for sym in SIGNAL_SYMBOLS:
        bars = bars_by_symbol.get(sym, pd.DataFrame())
        cand = evaluate_symbol_candidate(
            sym,
            bars,
            equity=equity,
            open_positions=open_syms,
            current_exposure=current_exposure,
            daily_pnl_pct=daily_pnl_pct,
            drawdown_pct=drawdown_pct,
            kill_switch_active=False,
            leverage=leverage,
            shorting_enabled=bool(acct.get("shorting_enabled", False)),
            etf_prices=prices,
            hourly_multipliers=hourly_multipliers,
            meta_model=meta_model,
            meta_threshold=meta_threshold,
            finnhub_key=finnhub_key,
            gemini_client=gemini_client,
            http_session=http_session,
            now_et=now,
            max_signal_age_min=max_signal_age_min,
            processed_signals=processed,
            session_close_et=close_et,
            max_notional=bp_left,
        )
        if not _execute_candidate(sym, cand):
            break

    # 3. Execute discovered individual stock opportunities (D33: Pre-Market & Intraday Scanner)
    opps_list = (
        stock_opportunities
        if stock_opportunities is not None
        else summary.get("premarket", {}).get("opportunities", [])
    )
    for opp in opps_list or []:
        opp_sym = str(opp.get("symbol", "")).upper().strip()
        if not opp_sym or opp_sym in SIGNAL_SYMBOLS:
            continue
        cand_opp = evaluate_mover_candidate(
            opp,
            equity=equity,
            open_positions=open_syms,
            current_exposure=current_exposure,
            daily_pnl_pct=daily_pnl_pct,
            drawdown_pct=drawdown_pct,
            kill_switch_active=False,
            shorting_enabled=bool(acct.get("shorting_enabled", False)),
            prices=prices,
            now_et=now,
            processed_signals=processed,
            session_close_et=close_et,
            max_notional=bp_left,
        )
        if not _execute_candidate(opp_sym, cand_opp):
            break

    journal["processed_signals"] = sorted(processed)
    return _finish("ok", {"orders": orders_submitted, "decisions": decisions, "management": mgmt})


# -------------------------------------------------------------------------------- EOD
def run_end_of_day_learning(
    *,
    state_dir: Path,
    adapter: AlpacaPaperAdapter,
    closed_trades_today: list[dict[str, Any]] | None = None,
    historical_X: pd.DataFrame | None = None,
    historical_y: pd.Series | None = None,
    recent_X: pd.DataFrame | None = None,
    recent_y: pd.Series | None = None,
    gemini_client: Any | None = None,
    http_session: Any | None = None,
    sync_github: bool = False,
    github_token: str | None = None,
    send_alerts: bool = True,
    bars_by_symbol: dict[str, pd.DataFrame] | None = None,
    prices: dict[str, float] | None = None,
    now_et: datetime | None = None,
) -> dict[str, Any]:
    """Flatten remaining positions, record today's trades with lessons, and retrain daily."""
    now = _now_et(now_et)
    today = now.strftime("%Y-%m-%d")
    store = StateStore(state_dir)
    journal = store.read_journal()

    open_before = adapter.get_open_positions()
    closed_count = 0
    if open_before:
        closed_count = adapter.liquidate_all()
        for sym in open_before:
            if sym in journal.get("open_trades", {}):
                journal["open_trades"][sym].setdefault("exit_reason_pending", "eod")
    remaining = _wait_for_closed(adapter, set(open_before)) if open_before else {}
    recorded = record_closed_trades(
        store,
        adapter,
        journal,
        remaining,
        bars_by_symbol=bars_by_symbol,
        now_et=now,
        gemini_client=gemini_client,
        send_alerts=send_alerts,
        http_session=http_session,
    )

    lessons: list[str] = [str(t.get("lesson", "")) for t in recorded]
    for tr in closed_trades_today or []:
        lessons.append(
            _finalize_trade(
                store,
                tr,
                gemini_client=gemini_client,
                send_alerts=send_alerts,
                http_session=http_session,
            )
        )

    trades_df = store.read_trades()
    mults = compute_hourly_multipliers(trades_df)

    retrained = False
    meta_stats: dict[str, Any] = {}
    if (
        historical_X is not None
        and historical_y is not None
        and recent_X is not None
        and recent_y is not None
    ):
        res = retrain_on_daily_trades(historical_X, historical_y, recent_X, recent_y)
        retrained = res is not None
    else:
        model, meta_stats = fit_meta_model_from_dataset(store)
        retrained = model is not None

    prev_stats = store.read_learning_stats()
    learning_payload = {
        **{k: v for k, v in prev_stats.items() if k not in ("pipeline",)},
        **meta_stats,
        "updated_at": now.isoformat(),
        "total_trades_analyzed": int(len(trades_df)),
        "hourly_multipliers": {str(k): round(float(v), 4) for k, v in mults.items()},
        "retrained_today": retrained,
        "last_lessons": lessons[-5:],
    }
    if "updated_threshold" in meta_stats:
        learning_payload["meta_threshold"] = float(meta_stats["updated_threshold"])
    store.write_learning_stats(learning_payload)

    journal["last_eod_date"] = today
    journal["processed_signals"] = [
        k for k in journal.get("processed_signals", []) if f"|{today}T" in k
    ]
    store.write_journal(journal)

    summary = initialize_live_paper_state(
        state_dir,
        adapter=adapter,
        sync_github=sync_github,
        github_token=github_token,
        session=http_session,
        spy_price=(prices or {}).get("SPY"),
        now_et=now,
    )

    todays = (
        trades_df.loc[trades_df["exit_time"].astype(str).str.startswith(today)]
        if not trades_df.empty and "exit_time" in trades_df.columns
        else trades_df
    )
    n_today = int(len(todays))
    wins_today = int((pd.to_numeric(todays["pnl"], errors="coerce") > 0).sum()) if n_today else 0
    if send_alerts:
        send_daily_summary_alert(
            date=today,
            equity=float(summary["equity"]),
            daily_pnl=float(summary["today_pnl"]),
            daily_pnl_pct=float(summary["today_pnl_pct"]),
            total_pnl=float(summary["total_pnl"]),
            total_pnl_pct=float(summary["total_pnl_pct"]),
            trades_count=n_today,
            wins_count=wins_today,
            drawdown_pct=float(summary["current_drawdown_pct"]),
            mode="PAPER",
            session=http_session,
        )

    return {
        "liquidated_positions": closed_count,
        "new_trades_recorded": len(recorded) + len(closed_trades_today or []),
        "lessons": lessons,
        "hourly_multipliers": mults,
        "summary": summary,
    }


# ------------------------------------------------------------------------------- KILL
def run_kill_switch(
    *,
    state_dir: Path,
    adapter: AlpacaPaperAdapter,
    reason: str = "Declanșat manual de proprietar din Dashboard / CLI",
    sync_github: bool = False,
    github_token: str | None = None,
    send_alerts: bool = True,
    http_session: Any | None = None,
    bars_by_symbol: dict[str, pd.DataFrame] | None = None,
    now_et: datetime | None = None,
) -> dict[str, Any]:
    """Activate emergency kill switch, close all open positions, and sync state."""
    now = _now_et(now_et)
    store = StateStore(state_dir)
    store.set_kill_switch(active=True, reason=reason, triggered_at=now.isoformat())
    journal = store.read_journal()
    open_before = adapter.get_open_positions()
    closed_count = adapter.liquidate_all()
    for sym in open_before:
        if sym in journal.get("open_trades", {}):
            journal["open_trades"][sym]["exit_reason_pending"] = "kill"
    remaining = _wait_for_closed(adapter, set(open_before)) if open_before else {}
    record_closed_trades(
        store,
        adapter,
        journal,
        remaining,
        bars_by_symbol=bars_by_symbol,
        now_et=now,
        send_alerts=send_alerts,
        http_session=http_session,
    )
    store.write_journal(journal)
    summary = initialize_live_paper_state(
        state_dir,
        adapter=adapter,
        sync_github=sync_github,
        github_token=github_token,
        session=http_session,
        now_et=now,
    )
    if sync_github:
        sync_state_dir_to_github(
            state_dir=state_dir, token=github_token, session=http_session, files=(KILL_SWITCH_FILE,)
        )
    if send_alerts:
        send_kill_alert(
            reason=reason,
            equity=float(summary.get("equity", 500.0)),
            closed_positions=closed_count,
            mode="PAPER",
            session=http_session,
        )
    return {
        "active": True,
        "reason": reason,
        "closed_positions": closed_count,
        "equity": summary.get("equity", 500.0),
    }


def reset_kill_switch(
    *,
    state_dir: Path,
    sync_github: bool = False,
    github_token: str | None = None,
    http_session: Any | None = None,
) -> dict[str, Any]:
    """Deactivate the KILL switch (owner decision; trading resumes on the next scheduled run)."""
    store = StateStore(state_dir)
    store.set_kill_switch(active=False, reason="Resetat de proprietar", triggered_at=None)
    if sync_github:
        sync_state_dir_to_github(
            state_dir=state_dir, token=github_token, session=http_session, files=(KILL_SWITCH_FILE,)
        )
    return store.read_kill_switch()


# ------------------------------------------------------------------- scheduled cycle
def run_scheduled_cycle(
    *,
    state_dir: Path,
    adapter: AlpacaPaperAdapter,
    load_bars: Callable[[], dict[str, pd.DataFrame]],
    load_prices: Callable[[], dict[str, float]],
    load_opportunities: Callable[[], list[dict[str, Any]]] | None = None,
    leverage: int = 2,
    now_fn: Callable[[], datetime] | None = None,
    sleep_fn: Callable[[float], None] = time.sleep,
    before_step: Callable[[], Any] | None = None,
    max_wait_min: float = DEFAULT_MAX_WAIT_MIN,
    finnhub_key: str | None = None,
    gemini_client: Any | None = None,
    http_session: Any | None = None,
    sync_github: bool = False,
    github_token: str | None = None,
    send_alerts: bool = True,
) -> dict[str, Any]:
    """One GitHub Actions run: wait for the next D1b event, trade/manage, then EOD if due."""
    clock = now_fn or (lambda: _now_et())
    plan = plan_auto_run(clock(), max_wait_min=max_wait_min)
    if plan["action"] == "closed":
        return {"status": "skipped", "plan": plan}
    if plan["action"] == "wait":
        sleep_fn(float(plan["sleep_s"]))
    if before_step is not None:
        before_step()  # e.g. pull the freshest state from the `state` branch after waiting

    now = clock()
    opps = load_opportunities() if load_opportunities is not None else None
    step = run_trading_step(
        state_dir=state_dir,
        adapter=adapter,
        bars_by_symbol=load_bars(),
        leverage=leverage,
        finnhub_key=finnhub_key,
        gemini_client=gemini_client,
        http_session=http_session,
        sync_github=sync_github,
        github_token=github_token,
        send_alerts=send_alerts,
        prices=load_prices(),
        now_et=now,
        stock_opportunities=opps,
    )
    result: dict[str, Any] = {"status": step["status"], "plan": plan, "step": step}

    bounds = session_bounds(now)
    store = StateStore(state_dir)
    if bounds is not None and step["status"] in ("ok", "halted"):
        time_exit = d1b_event_times(*bounds)["time_exit"]
        if now >= time_exit and store.read_journal().get("last_eod_date") != now.strftime(
            "%Y-%m-%d"
        ):
            result["eod"] = run_end_of_day_learning(
                state_dir=state_dir,
                adapter=adapter,
                gemini_client=gemini_client,
                http_session=http_session,
                sync_github=sync_github,
                github_token=github_token,
                send_alerts=send_alerts,
                prices=load_prices(),
                now_et=now,
            )
    return result
