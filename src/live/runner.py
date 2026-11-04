"""Intraday paper trading loop, daily self-learning, and emergency kill switch (Faza B, B6c).

Orchestrates:
- Real-time signal evaluation on SPY and QQQ via D1b (VWAP & Ladder #1, Long+Short+Leverage D31).
- No artificial daily trade count cap: takes every trade passing D1b + AI + Risk Guard.
- End-of-day flat liquidation (15:59 ET), Romanian post-mortem, and daily model retraining.
- Real-time synchronization of `state/` to the `state` branch on GitHub for the Vercel dashboard.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd

from src.ai.autopsy import build_autopsy_record
from src.ai.daily_learner import compute_hourly_multipliers, retrain_on_daily_trades
from src.ai.meta_label import FEATURE_COLUMNS, compute_feature_frame
from src.ai.veto import check_news_veto, fetch_recent_news
from src.alerts.telegram import (
    send_daily_summary_alert,
    send_entry_alert,
    send_exit_alert,
    send_kill_alert,
)
from src.backtest.intraday_costs import STOCK_HALF_SPREAD
from src.broker.alpaca_paper import (
    AlpacaPaperAdapter,
    make_client_order_id,
    resolve_execution_instrument,
)
from src.live.state_writer import sync_state_dir_to_github, write_state_files
from src.risk.guard import (
    MAX_DRAWDOWN_KILL_PCT,
    MAX_RISK_PER_TRADE_PCT,
    MAX_TOTAL_EXPOSURE,
    evaluate_order_risk,
    symbol_family,
)
from src.state.store import (
    TRADE_COLUMNS,
    StateStore,
    init_clean_paper_state,
    reconcile_positions,
)
from src.strategies.intraday_d1 import D1bParams, generate_d1b_signals

logger = logging.getLogger(__name__)
NY_TZ = ZoneInfo("America/New_York")


def _now_et(now: datetime | None = None) -> datetime:
    dt = now or datetime.now(UTC)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(NY_TZ)


def _minutes_to_close(ts_et: datetime) -> float:
    close_dt = ts_et.replace(hour=16, minute=0, second=0, microsecond=0)
    return (close_dt - ts_et).total_seconds() / 60.0


def initialize_live_paper_state(
    state_dir: Path,
    adapter: AlpacaPaperAdapter | None = None,
    *,
    initial_capital: float = 500.0,
    as_of_date: str | None = None,
    sync_github: bool = False,
    github_token: str | None = None,
    session: Any | None = None,
) -> dict[str, Any]:
    """Initialize or refresh `state/` from the real Alpaca Paper account (`is_sample: False`)."""
    now_et = _now_et()
    date_str = as_of_date or now_et.strftime("%Y-%m-%d")
    store = StateStore(state_dir)

    if not store.summary_path.exists():
        init_clean_paper_state(
            state_dir,
            initial_capital=initial_capital,
            date_str=date_str,
            updated_at=now_et.isoformat(),
        )

    summary = store.read_summary()
    equity_df = store.read_equity()
    trades_df = store.read_trades()

    if adapter is not None:
        acct = adapter.get_account_state()
        broker_positions = adapter.get_open_positions()
        equity = float(acct.get("equity", initial_capital))
        init_cap = float(summary.get("initial_capital", initial_capital))
        total_pnl = round(equity - init_cap, 2)
        total_pnl_pct = round((total_pnl / init_cap) * 100.0, 2) if init_cap > 0 else 0.0

        prev_equity = (
            float(equity_df["bot_equity"].iloc[-1])
            if not equity_df.empty and len(equity_df) > 1
            else init_cap
        )
        today_pnl = round(equity - prev_equity, 2)
        today_pnl_pct = round((today_pnl / prev_equity) * 100.0, 2) if prev_equity > 0 else 0.0

        peak_eq = max([init_cap, equity] + equity_df["bot_equity"].astype(float).tolist())
        curr_dd_pct = round(((equity - peak_eq) / peak_eq) * 100.0, 2) if peak_eq > 0 else 0.0
        prev_max_dd = float(summary.get("max_drawdown_pct", 0.0))
        max_dd_pct = round(min(prev_max_dd, curr_dd_pct), 2)

        open_list: list[dict[str, Any]] = []
        for sym, pos in sorted(broker_positions.items()):
            entry_p = float(pos.get("entry_price", 0.0))
            curr_p = float(pos.get("current_price", entry_p))
            unr_pnl = float(pos.get("unrealized_pnl", 0.0))
            stop_p = round(entry_p * 0.995, 4) if entry_p > 0 else 0.0
            open_list.append(
                {
                    "symbol": sym,
                    "direction": pos.get("direction", "long"),
                    "entry_time": now_et.isoformat(),
                    "qty": round(float(pos.get("qty", 0.0)), 4),
                    "entry_price": round(entry_p, 4),
                    "current_price": round(curr_p, 4),
                    "stop": stop_p,
                    "initial_stop": stop_p,
                    "unrealized_pnl": round(unr_pnl, 2),
                    "unrealized_r": 0.0,
                    "entry_reason": "Poziție activă sincronizată din contul Alpaca Paper.",
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
                "updated_at": now_et.isoformat(),
                "positions": open_list,
            }
        )
        store.write_positions(open_list)

        if equity_df.empty:
            equity_df = pd.DataFrame(
                [
                    {
                        "date": date_str,
                        "bot_equity": round(equity, 2),
                        "spy_buy_hold": round(init_cap, 2),
                        "daily_pnl": today_pnl,
                        "drawdown_pct": curr_dd_pct,
                    }
                ]
            )
        elif str(equity_df.iloc[-1]["date"]) == date_str:
            equity_df.loc[equity_df.index[-1], "bot_equity"] = round(equity, 2)
            equity_df.loc[equity_df.index[-1], "daily_pnl"] = today_pnl
            equity_df.loc[equity_df.index[-1], "drawdown_pct"] = curr_dd_pct
        else:
            equity_df = pd.concat(
                [
                    equity_df,
                    pd.DataFrame(
                        [
                            {
                                "date": date_str,
                                "bot_equity": round(equity, 2),
                                "spy_buy_hold": float(equity_df.iloc[-1]["spy_buy_hold"]),
                                "daily_pnl": today_pnl,
                                "drawdown_pct": curr_dd_pct,
                            }
                        ]
                    ),
                ],
                ignore_index=True,
            )

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
    meta_threshold: float = 0.52,
    finnhub_key: str | None = None,
    gemini_client: Any | None = None,
    http_session: Any | None = None,
) -> dict[str, Any]:
    """Evaluate the latest closed 1-minute bar on `symbol` through D1b + AI + Risk Guard."""
    if bars.empty:
        return {"action": "none", "reason": "Nu există bare intraday disponibile."}

    # D31: Both Long (+1) and Short (-1) signals enabled on D1b
    sig_df = generate_d1b_signals(bars, D1bParams())
    last_idx = sig_df.index[-1]
    last_row = sig_df.iloc[-1]
    raw_sig = int(last_row.get("entry", 0))
    if raw_sig == 0:
        return {"action": "none", "reason": "Niciun semnal D1b pe bara curentă."}

    direction = "long" if raw_sig > 0 else "short"
    signal_price = float(bars["close"].iloc[-1])
    signal_stop = float(last_row["stop"])
    signal_target = (
        float(last_row["target"]) if "target" in last_row and pd.notna(last_row["target"]) else None
    )
    base_reason = str(last_row.get("entry_reason") or f"D1b ({direction.upper()}) pe {symbol}")

    # 1. Meta-labeling + Daily Learner hourly multiplier
    feats = compute_feature_frame(bars)
    feat_row = feats.iloc[-1]
    meta_prob = 0.60
    if meta_model is not None:
        X_last = feat_row[list(FEATURE_COLUMNS)].to_frame().T.fillna(0.0)
        prob_arr = meta_model.predict_proba(X_last)
        meta_prob = float(prob_arr[0, 1])
        if meta_prob < meta_threshold:
            msg = f"Filtru AI meta_label: probabilitate {meta_prob:.2f} < {meta_threshold:.2f}"
            return {"action": "skip", "reason": msg}

    ts_et = (
        last_idx.to_pydatetime().astimezone(NY_TZ)
        if hasattr(last_idx, "to_pydatetime")
        else _now_et()
    )
    hour_et = ts_et.hour
    hour_mult = float((hourly_multipliers or {}).get(hour_et, 1.0))
    if hour_mult <= 0.0:
        return {
            "action": "skip",
            "reason": f"Filtru învățare zilnică: ora {hour_et}:00 ET dezactivată.",
        }

    # 2. News veto (Finnhub + Gemini / deterministic crisis keywords)
    news_items = fetch_recent_news(symbol, finnhub_key=finnhub_key or "", session=http_session)
    headlines = [item["headline"] for item in news_items if item.get("headline")]
    allow_news, news_reason = check_news_veto(symbol, direction, headlines, client=gemini_client)
    if not allow_news:
        return {"action": "skip", "reason": f"Veto știri: {news_reason}"}

    # 3. Map signal to execution instrument (D31: Short SPY/QQQ -> SH/SDS/PSQ/QID on 500$ account)
    raw_dist = abs(signal_price - signal_stop)
    if raw_dist <= 0:
        return {"action": "skip", "reason": "Distanță stop-loss invalidă (0)."}

    risk_budget = equity * MAX_RISK_PER_TRADE_PCT * min(hour_mult, 1.0)
    raw_qty = max(0.01, risk_budget / raw_dist)

    prices = etf_prices or {}
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
        instrument_price=prices.get(symbol),
    )
    exec_symbol = str(exec_spec["exec_symbol"])
    exec_dir = "long" if exec_spec["side"] == "buy" else "short"
    exec_price = float(exec_spec["entry_price"])
    exec_stop = float(exec_spec["stop_price"])
    stop_dist = abs(exec_price - exec_stop)
    if stop_dist <= 0:
        return {"action": "skip", "reason": "Distanță stop-loss invalidă (0)."}

    # 4. Position sizing capped by risk per trade (0.5% * hour_mult) and remaining exposure
    qty_by_risk = risk_budget / stop_dist
    remaining_notional = max(0.0, equity * MAX_TOTAL_EXPOSURE - current_exposure)
    qty_by_notional = (remaining_notional * 0.98) / exec_price if exec_price > 0 else 0.0
    qty = round(min(float(exec_spec["qty"]), qty_by_risk, qty_by_notional), 4)
    if qty <= 0.0:
        return {"action": "skip", "reason": "Cantitate calculată 0 (expunere plină)."}

    risk_dollars = qty * stop_dist
    typ_spread = STOCK_HALF_SPREAD * 2.0
    mins_to_close = _minutes_to_close(ts_et)

    allowed, risk_reason = evaluate_order_risk(
        symbol=exec_symbol,
        direction=exec_dir,
        entry_price=exec_price,
        stop=exec_stop,
        qty=qty,
        equity=equity,
        current_exposure=current_exposure,
        open_positions=open_positions,
        daily_pnl_pct=daily_pnl_pct,
        drawdown_pct=drawdown_pct,
        timestamp=pd.Timestamp(ts_et),
        minutes_to_close=mins_to_close,
        current_spread=typ_spread,
        typical_spread=typ_spread,
        kill_switch_active=kill_switch_active,
    )
    if not allowed:
        return {"action": "skip", "reason": risk_reason}

    exec_note = f"D31: {symbol} {direction.upper()} -> BUY {exec_symbol} ({exec_spec['leverage']}x)"
    full_reason = f"{base_reason} · {exec_note} · AI p={meta_prob:.2f} · mult_oră={hour_mult:.2f}"
    return {
        "action": "enter",
        "signal_symbol": symbol,
        "exec_symbol": exec_symbol,
        "signal_direction": direction,
        "exec_direction": exec_dir,
        "qty": qty,
        "entry_price": exec_price,
        "stop_price": exec_stop,
        "target_price": exec_spec["target_price"],
        "risk_dollars": risk_dollars,
        "risk_pct": risk_dollars / equity if equity > 0 else 0.0,
        "leverage": int(exec_spec["leverage"]),
        "timestamp": ts_et.strftime("%Y%m%dT%H%M"),
        "reason": full_reason,
    }


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
) -> dict[str, Any]:
    """Run one intraday evaluation cycle across `SPY` and `QQQ` on Alpaca Paper."""
    store = StateStore(state_dir)
    if not store.summary_path.exists():
        initialize_live_paper_state(
            state_dir,
            adapter=adapter,
            sync_github=sync_github,
            github_token=github_token,
            session=http_session,
        )

    kill_state = store.read_kill_switch()
    if kill_state.get("active"):
        return {"status": "halted", "reason": "KILL switch este activ.", "orders": []}

    acct = adapter.get_account_state()
    broker_positions = adapter.get_open_positions()
    local_positions = store.read_positions()
    recon = reconcile_positions(local_positions, broker_positions)
    store.write_positions(recon["synced_positions"])

    summary = store.read_summary()
    equity = float(acct.get("equity", summary.get("equity", 500.0)))
    init_cap = float(summary.get("initial_capital", 500.0))
    equity_df = store.read_equity()
    prev_eq = (
        float(equity_df["bot_equity"].iloc[-1])
        if not equity_df.empty and len(equity_df) > 1
        else init_cap
    )
    daily_pnl = equity - prev_eq
    daily_pnl_pct = daily_pnl / prev_eq if prev_eq > 0 else 0.0

    peak_eq = max([init_cap, equity] + equity_df["bot_equity"].astype(float).tolist())
    drawdown_pct = (equity - peak_eq) / peak_eq if peak_eq > 0 else 0.0

    if drawdown_pct <= MAX_DRAWDOWN_KILL_PCT:
        run_kill_switch(
            state_dir=state_dir,
            adapter=adapter,
            reason=f"Drawdown maxim atins ({drawdown_pct * 100:.2f}% <= -15%)",
            sync_github=sync_github,
            github_token=github_token,
            send_alerts=send_alerts,
            http_session=http_session,
        )
        return {"status": "killed", "reason": "Drawdown maxim atins (-15%)", "orders": []}

    learning_stats = store.read_learning_stats()
    raw_mults = learning_stats.get("hourly_multipliers") or {}
    hourly_multipliers = {int(k): float(v) for k, v in raw_mults.items()}

    open_syms = set(broker_positions.keys())
    current_exposure = sum(
        abs(
            float(
                p.get("market_value", float(p.get("qty", 0.0)) * float(p.get("current_price", 0.0)))
            )
        )
        for p in broker_positions.values()
    )

    orders_submitted: list[dict[str, Any]] = []
    decisions: dict[str, Any] = {}

    for sym in ("SPY", "QQQ"):
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
            hourly_multipliers=hourly_multipliers,
            meta_model=meta_model,
            finnhub_key=finnhub_key,
            gemini_client=gemini_client,
            http_session=http_session,
        )
        decisions[sym] = cand
        if cand.get("action") != "enter":
            continue

        cid = make_client_order_id(cand["exec_symbol"], cand["timestamp"], cand["signal_direction"])
        order_res = adapter.submit_order_with_stop(
            symbol=sym,
            direction=cand["signal_direction"],
            qty=cand["qty"],
            entry_price=cand["entry_price"],
            stop_price=cand["stop_price"],
            target_price=cand["target_price"],
            client_order_id=cid,
            leverage=leverage,
        )
        orders_submitted.append(
            {**order_res, "exec_symbol": order_res.get("symbol", cand["exec_symbol"])}
        )
        open_syms.add(cand["exec_symbol"])
        open_syms.add(symbol_family(cand["exec_symbol"]))
        current_exposure += cand["qty"] * cand["entry_price"]

        if send_alerts:
            send_entry_alert(
                symbol=cand["exec_symbol"],
                direction=cand["signal_direction"],
                qty=cand["qty"],
                entry_price=cand["entry_price"],
                stop=cand["stop_price"],
                risk_pct=cand["risk_pct"],
                reason=cand["reason"],
                strategy="D1b (VWAP & Ladder #1)",
                mode="PAPER",
                session=http_session,
            )

    updated_summary = initialize_live_paper_state(
        state_dir,
        adapter=adapter,
        initial_capital=init_cap,
        sync_github=sync_github,
        github_token=github_token,
        session=http_session,
    )
    return {
        "status": "ok",
        "equity": updated_summary["equity"],
        "orders": orders_submitted,
        "decisions": decisions,
    }


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
) -> dict[str, Any]:
    """Close remaining intraday positions at 15:59 ET, write lessons, and retrain daily learner."""
    store = StateStore(state_dir)
    closed_count = adapter.liquidate_all()

    trades_df = store.read_trades()
    new_trades = closed_trades_today or []
    lessons: list[str] = []

    for tr in new_trades:
        rec = build_autopsy_record(tr, client=gemini_client)
        store.append_autopsy(rec)
        lesson = rec["lesson"]
        lessons.append(lesson)

        base_reason = str(tr.get("entry_reason", "D1b intraday"))
        enriched_reason = f"{base_reason} | Lecție: {lesson}"
        row = {col: tr.get(col, "") for col in TRADE_COLUMNS}
        row["entry_reason"] = enriched_reason
        trades_df = pd.concat([trades_df, pd.DataFrame([row])], ignore_index=True)

        if send_alerts:
            send_exit_alert(
                symbol=str(tr.get("symbol", "SPY")),
                direction=str(tr.get("direction", "long")),
                pnl=float(tr.get("pnl", 0.0)),
                r_multiple=float(tr.get("r_multiple", 0.0)),
                exit_reason=str(tr.get("exit_reason", "eod")),
                exit_price=float(tr.get("exit_price", 0.0)),
                lesson=lesson,
                mode="PAPER",
                session=http_session,
            )

    store.write_trades(trades_df)

    # Update hourly multipliers from full trade history
    mults = compute_hourly_multipliers(trades_df)
    retrained = False
    if (
        historical_X is not None
        and historical_y is not None
        and recent_X is not None
        and recent_y is not None
    ):
        model = retrain_on_daily_trades(historical_X, historical_y, recent_X, recent_y)
        retrained = model is not None

    learning_payload = {
        "updated_at": _now_et().isoformat(),
        "total_trades_analyzed": int(len(trades_df)),
        "hourly_multipliers": {str(k): round(float(v), 4) for k, v in mults.items()},
        "retrained_today": retrained,
        "last_lessons": lessons[-5:],
    }
    store.write_learning_stats(learning_payload)

    summary = initialize_live_paper_state(
        state_dir,
        adapter=adapter,
        sync_github=sync_github,
        github_token=github_token,
        session=http_session,
    )

    if send_alerts:
        wins_today = sum(1 for t in new_trades if float(t.get("pnl", 0.0)) > 0)
        send_daily_summary_alert(
            date=_now_et().strftime("%Y-%m-%d"),
            equity=float(summary["equity"]),
            daily_pnl=float(summary["today_pnl"]),
            daily_pnl_pct=float(summary["today_pnl_pct"]),
            total_pnl=float(summary["total_pnl"]),
            total_pnl_pct=float(summary["total_pnl_pct"]),
            trades_count=len(new_trades),
            wins_count=wins_today,
            drawdown_pct=float(summary["current_drawdown_pct"]),
            mode="PAPER",
            session=http_session,
        )

    return {
        "liquidated_positions": closed_count,
        "new_trades_recorded": len(new_trades),
        "lessons": lessons,
        "hourly_multipliers": mults,
        "summary": summary,
    }


def run_kill_switch(
    *,
    state_dir: Path,
    adapter: AlpacaPaperAdapter,
    reason: str = "Declanșat manual de proprietar din Dashboard / CLI",
    sync_github: bool = False,
    github_token: str | None = None,
    send_alerts: bool = True,
    http_session: Any | None = None,
) -> dict[str, Any]:
    """Activate emergency kill switch, close all open positions, and sync state."""
    store = StateStore(state_dir)
    closed_count = adapter.liquidate_all()
    store.set_kill_switch(active=True, reason=reason, triggered_at=_now_et().isoformat())
    summary = initialize_live_paper_state(
        state_dir,
        adapter=adapter,
        sync_github=sync_github,
        github_token=github_token,
        session=http_session,
    )
    if sync_github:
        sync_state_dir_to_github(state_dir=state_dir, token=github_token, session=http_session)
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
