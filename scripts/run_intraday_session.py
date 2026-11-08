#!/usr/bin/env python3
"""CLI entrypoint for Faza B intraday paper trading on Alpaca Paper (B6c, B6d).

Modes:
  --auto        Scheduled GitHub Actions run: restore `state/` from the `state` branch, wait for
                the next D1b event (check bar close or 15:30 time exit, at most 12 minutes),
                manage open positions, take fresh signals, and run EOD learning after 15:30 ET.
  --init-state  Initialize/refresh `state/` from the real 500$ Alpaca Paper account
                (`is_sample: False`) and push to the `state` branch on GitHub.
  --once        Run a single intraday evaluation cycle now (no waiting).
  --eod         Run end-of-day liquidation, post-mortem, and daily learning now.
  --kill        Trigger emergency KILL switch, liquidate all open positions, and sync `state/`.
  --reset-kill  Deactivate the KILL switch (owner decision).
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import socket
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from alpaca.data.historical import StockHistoricalDataClient  # noqa: E402
from alpaca.data.requests import StockLatestTradeRequest  # noqa: E402
from alpaca.trading.client import TradingClient  # noqa: E402

from src.ai.market_scanner import (  # noqa: E402
    SINGLE_STOCK_INVERSE_MAP,
    scan_market_opportunities,
)
from src.ai.premarket import (  # noqa: E402
    build_premarket_briefing,
    format_premarket_telegram_message,
)
from src.ai.weekend_research import run_weekend_session  # noqa: E402
from src.alerts.telegram import send_telegram_message  # noqa: E402
from src.broker.alpaca_paper import AlpacaPaperAdapter  # noqa: E402
from src.config import settings  # noqa: E402
from src.data.intraday import (  # noqa: E402
    fetch_minute_bars,
    filter_regular_session,
    load_minute_bars,
    nyse_sessions,
)
from src.data.market_time import NY_TZ  # noqa: E402
from src.live.runner import (  # noqa: E402
    RELAY_START,
    initialize_live_paper_state,
    live_window,
    reset_kill_switch,
    run_end_of_day_learning,
    run_kill_switch,
    run_scheduled_cycle,
    run_trading_step,
)
from src.live.state_writer import (  # noqa: E402
    KILL_SWITCH_FILE,
    SYNCED_STATE_FILES,
    acquire_engine_lease,
    enable_push_dedupe,
    fetch_github_state_file,
    fetch_remote_kill_switch,
    pull_state_dir_from_github,
    release_engine_lease,
    sync_state_dir_to_github,
)
from src.risk.guard import ALLOWED_SYMBOLS  # noqa: E402
from src.state.store import StateStore  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("intraday_session")

SIGNAL_SYMBOLS = ("SPY", "QQQ")
GEMINI_TIMEOUT_MS = 20_000  # one Gemini call can never block a 60 s trading cycle (B6f)
PRICE_MAX_AGE_S = 600.0  # IEX last trade older than 10 min = stale price, not used to trade
OPP_SCAN_COOLDOWN_S = 600.0  # market-wide mover scan at most every 10 min (persisted in state)
OPP_MAX_AGE_S = 1800.0  # an AI opportunity older than 30 min is not executed
PREMARKET_REFRESH_S = 900.0  # pre-market briefing refreshed at most every 15 min


def _load_recent_bars(
    data_client: StockHistoricalDataClient,
    symbol: str,
    lookback_days: int = 28,
) -> pd.DataFrame:
    """Fetch recent regular-session 1-minute bars (real-time IEX + local SIP cache fallback)."""
    now_utc = datetime.now(UTC)
    start_utc = now_utc - timedelta(days=lookback_days)
    end_utc = now_utc - timedelta(minutes=1)  # drop incomplete current minute bar
    sessions = nyse_sessions(start_utc.date(), now_utc.date())

    frames: list[pd.DataFrame] = []
    try:
        cached = load_minute_bars(symbol, feed="sip", start=start_utc.strftime("%Y-%m-%d"))
        if not cached.empty:
            frames.append(cached)
    except Exception:  # noqa: BLE001
        pass

    try:
        live_iex = fetch_minute_bars(
            data_client, symbol=symbol, start=start_utc, end=end_utc, feed="iex"
        )
        if not live_iex.empty and not sessions.empty:
            live_filtered = filter_regular_session(live_iex, sessions)
            if not live_filtered.empty:
                frames.append(live_filtered)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Nu s-au putut descărca barele IEX live pentru %s: %s", symbol, exc)

    if not frames:
        return pd.DataFrame()
    combined = pd.concat(frames).sort_index()
    combined = combined[~combined.index.duplicated(keep="last")]
    return combined


def _load_all_bars(data_client: StockHistoricalDataClient) -> dict[str, pd.DataFrame]:
    """Bars for SPY and QQQ; retries briefly if the just-closed minute is not published yet."""
    out: dict[str, pd.DataFrame] = {}
    for sym in SIGNAL_SYMBOLS:
        bars = pd.DataFrame()
        for attempt in range(3):
            bars = _load_recent_bars(data_client, sym)
            # Start of the last fully closed minute bar (e.g. 10:11 when it is 10:12:08)
            expected = (datetime.now(UTC) - timedelta(minutes=1)).replace(second=0, microsecond=0)
            if not bars.empty and bars.index[-1] >= pd.Timestamp(expected):
                break
            if attempt < 2:
                time.sleep(5)
        out[sym] = bars
    return out


def _load_prices(
    data_client: StockHistoricalDataClient, state_dir: Path | None = None
) -> dict[str, float]:
    """Latest IEX trade price for allowed ETFs, inverse ETFs, open positions & scanned movers."""
    extra_syms: set[str] = set(SINGLE_STOCK_INVERSE_MAP.values())
    if state_dir is not None:
        try:
            store = StateStore(state_dir)
            journal = store.read_journal()
            for exec_sym, tr in (journal.get("open_trades") or {}).items():
                extra_syms.add(str(exec_sym).upper())
                if tr.get("signal_symbol"):
                    extra_syms.add(str(tr["signal_symbol"]).upper())
            summary = store.read_summary()
            for opp in summary.get("premarket", {}).get("opportunities", []) or []:
                if opp.get("symbol"):
                    extra_syms.add(str(opp["symbol"]).upper())
        except Exception:  # noqa: BLE001
            pass
    syms = sorted({s for s in (set(ALLOWED_SYMBOLS) | extra_syms) if s and s.isalpha()})
    try:
        latest = data_client.get_stock_latest_trade(
            StockLatestTradeRequest(symbol_or_symbols=syms, feed="iex")
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Nu s-au putut citi prețurile curente: %s", exc)
        return {}
    return _fresh_prices(latest, syms, datetime.now(UTC))


def _fresh_prices(latest: Any, syms: list[str], now_utc: datetime) -> dict[str, float]:
    """Drop IEX last trades older than PRICE_MAX_AGE_S during the regular session (B6f).

    Thin small caps can have an IEX last trade many minutes old; sizing a stop on it put the stop
    far from the real fill. Outside regular hours every last trade is kept (pre-market display).
    """
    now_et = now_utc.astimezone(NY_TZ)
    in_session = (9, 30) <= (now_et.hour, now_et.minute) < (16, 0)
    out: dict[str, float] = {}
    for s in syms:
        trade = latest.get(s) if hasattr(latest, "get") else None
        price = float(getattr(trade, "price", 0.0) or 0.0) if trade is not None else 0.0
        if price <= 0:
            continue
        ts = getattr(trade, "timestamp", None)
        if in_session and isinstance(ts, datetime):
            ts_utc = ts if ts.tzinfo is not None else ts.replace(tzinfo=UTC)
            if (now_utc - ts_utc).total_seconds() > PRICE_MAX_AGE_S:
                continue
        out[s] = price
    return out


def _gemini_client():
    if not settings.GEMINI_API_KEY:
        return None
    try:
        from google import genai
        from google.genai import types

        # 20 s HTTP timeout: a hung Gemini call must never push a run past the 25 min job limit
        return genai.Client(
            api_key=settings.GEMINI_API_KEY,
            http_options=types.HttpOptions(timeout=GEMINI_TIMEOUT_MS),
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Clientul Gemini nu a putut fi creat: %s", type(exc).__name__)
        return None


def _compute_premarket_quotes(
    data_client: StockHistoricalDataClient,
) -> dict[str, dict[str, float]]:
    """Compute pre-market / current price vs previous regular-session close for SPY and QQQ."""
    now_utc = datetime.now(UTC)
    start_utc = now_utc - timedelta(days=7)
    prices = _load_prices(data_client)
    out: dict[str, dict[str, float]] = {}

    for sym in SIGNAL_SYMBOLS:
        prev_close = 0.0
        curr_price = float(prices.get(sym, 0.0))
        try:
            reg_bars = _load_recent_bars(data_client, sym, lookback_days=7)
            if not reg_bars.empty:
                prev_close = float(reg_bars["close"].iloc[-1])
        except Exception:  # noqa: BLE001
            pass

        try:
            ext_bars = fetch_minute_bars(
                data_client, symbol=sym, start=start_utc, end=now_utc, feed="iex"
            )
            if not ext_bars.empty:
                curr_price = float(ext_bars["close"].iloc[-1])
        except Exception:  # noqa: BLE001
            pass

        if prev_close <= 0 and curr_price > 0:
            prev_close = curr_price
        if curr_price <= 0 and prev_close > 0:
            curr_price = prev_close

        gap_pct = ((curr_price - prev_close) / prev_close * 100.0) if prev_close > 0 else 0.0
        out[sym] = {
            "price": round(curr_price, 2),
            "prev_close": round(prev_close, 2),
            "gap_pct": round(gap_pct, 2),
        }
    return out


def _parse_ts(value: Any) -> datetime | None:
    try:
        dt = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)


def _seconds_since(value: Any, now_utc: datetime) -> float:
    ts = _parse_ts(value)
    return (now_utc - ts).total_seconds() if ts is not None else float("inf")


def _recent_opportunities(
    items: list[dict[str, Any]], now_utc: datetime, max_age_s: float = OPP_MAX_AGE_S
) -> list[dict[str, Any]]:
    """Only opportunities evaluated in the last `max_age_s` may be executed (never yesterday's)."""
    return [o for o in items if _seconds_since(o.get("evaluated_at"), now_utc) <= max_age_s]


def _premarket_due(state_dir: Path, now_utc: datetime) -> bool:
    pm = StateStore(state_dir).read_summary().get("premarket") or {}
    return _seconds_since(pm.get("last_scan_at"), now_utc) >= PREMARKET_REFRESH_S


def _run_premarket_intelligence(
    *,
    state_dir: Path,
    data_client: StockHistoricalDataClient,
    gemini_client: Any,
    sync_github: bool = True,
    notify_telegram: bool = True,
) -> dict[str, Any]:
    """Scan pre-market prices, individual stock movers, news & financial reports.

    The Telegram briefing goes out at most once per day (date kept in state, B6f), so the relay
    chain's 15-minute runs do not resend it.
    """
    now_utc = datetime.now(UTC)
    today = now_utc.astimezone(NY_TZ).strftime("%Y-%m-%d")
    quotes = _compute_premarket_quotes(data_client)
    scan = scan_market_opportunities(
        api_key=settings.ALPACA_API_KEY,
        secret_key=settings.ALPACA_SECRET_KEY,
        finnhub_key=settings.FINNHUB_API_KEY,
        gemini_client=gemini_client,
        max_opportunities=6,
        state_dir=state_dir,
    )
    briefing = build_premarket_briefing(
        quotes=quotes,
        finnhub_key=settings.FINNHUB_API_KEY,
        gemini_client=gemini_client,
        opportunities=scan.get("opportunities", []),
        top_movers=scan.get("top_movers", []),
    )
    store = StateStore(state_dir)
    summary = store.read_summary()
    prev = summary.get("premarket") if isinstance(summary.get("premarket"), dict) else {}
    briefing["last_scan_at"] = now_utc.isoformat()
    briefing["telegram_sent_date"] = prev.get("telegram_sent_date")
    send_tg = notify_telegram and prev.get("telegram_sent_date") != today
    if send_tg:
        briefing["telegram_sent_date"] = today
    if summary:
        summary["premarket"] = briefing
        store.write_summary(summary)
        if sync_github:
            # summary.json only: this job must never overwrite a running session's journal
            sync_state_dir_to_github(
                state_dir, token=settings.GH_DISPATCH_TOKEN, files=("summary.json",)
            )
    if send_tg:
        send_telegram_message(format_premarket_telegram_message(briefing))
    return briefing


def _load_opportunities(
    state_dir: Path, gemini_client: Any, now_utc: datetime | None = None
) -> list[dict[str, Any]]:
    """Scan market-wide stock movers (at most every 10 min, persisted in state) + recent setups.

    The cooldown timestamp lives in `summary.json` (`premarket.last_scan_at`), so it survives the
    relay chain's new processes and also applies after an empty or failed scan (B6f).
    """
    now_utc = now_utc or datetime.now(UTC)
    store = StateStore(state_dir)
    summary = store.read_summary()
    pm = dict(summary.get("premarket") or {}) if isinstance(summary.get("premarket"), dict) else {}
    existing = _recent_opportunities(list(pm.get("opportunities") or []), now_utc)
    if _seconds_since(pm.get("last_scan_at"), now_utc) < OPP_SCAN_COOLDOWN_S:
        return existing

    scan: dict[str, Any] = {}
    try:
        scan = scan_market_opportunities(
            api_key=settings.ALPACA_API_KEY,
            secret_key=settings.ALPACA_SECRET_KEY,
            finnhub_key=settings.FINNHUB_API_KEY,
            gemini_client=gemini_client,
            max_opportunities=5,
            state_dir=state_dir,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Scanarea oportunităților pe acțiuni a eșuat: %s", exc)
    fresh = list(scan.get("opportunities", []) or [])
    pm["last_scan_at"] = now_utc.isoformat()
    if fresh:
        pm["opportunities"] = fresh
    if scan.get("top_movers"):
        pm["top_movers"] = scan["top_movers"]
    if summary:
        summary["premarket"] = pm
        store.write_summary(summary)
    by_sym: dict[str, dict[str, Any]] = {}
    for item in [*fresh, *existing]:
        sym = str(item.get("symbol", "")).upper()
        if sym and sym not in by_sym:
            by_sym[sym] = item
    return list(by_sym.values())


def _engine_id() -> str:
    run_id = os.environ.get("GITHUB_RUN_ID")
    if run_id:
        return f"gha-{run_id}-{os.environ.get('GITHUB_RUN_ATTEMPT', '1')}"
    return f"local-{socket.gethostname()}-{os.getpid()}"


class _EngineLease:
    """Single-engine guard: only the holder of state/engine_lock.json trades (B6f)."""

    def __init__(self, enabled: bool) -> None:
        self.enabled = enabled
        self.engine_id = _engine_id()
        self.valid_until = 0.0
        self.has_state = False

    def ensure(self) -> tuple[bool, bool]:
        """(held, needs_full_pull)."""
        if not self.enabled:
            fresh = not self.has_state
            self.has_state = True
            return True, fresh
        res = acquire_engine_lease(self.engine_id, token=settings.GH_DISPATCH_TOKEN)
        if res.get("held"):
            exp = _parse_ts(res.get("expires_at"))
            self.valid_until = exp.timestamp() if exp is not None else time.time() + 60.0
            fresh = bool(res.get("fresh")) or not self.has_state
            self.has_state = True
            return True, fresh
        if res.get("error") and time.time() < self.valid_until - 30.0:
            logger.warning("Lacăt: %s — continui pe lacătul încă valid.", res.get("reason"))
            return True, False
        logger.warning("Nu tranzacționez acum: %s", res.get("reason"))
        self.has_state = False
        return False, False

    def release(self) -> None:
        if self.enabled and self.has_state:
            release_engine_lease(self.engine_id, token=settings.GH_DISPATCH_TOKEN)


def _should_relay(now_utc: datetime | None = None) -> tuple[bool, str]:
    """Hand over to a next 15-minute run? Only on NYSE days, until 15 min before the close,
    while KILL is off and before today's end-of-day learning is done."""
    now_utc = now_utc or datetime.now(UTC)
    now_et = now_utc.astimezone(NY_TZ)
    try:
        window = live_window(now_et)
        if not window["relay"]:
            return False, str(window["reason"])
        if fetch_remote_kill_switch(token=settings.GH_DISPATCH_TOKEN) is True:
            return False, "KILL activ: lanțul se oprește până la resetare."
        raw = fetch_github_state_file("live_journal.json", token=settings.GH_DISPATCH_TOKEN)
        if raw and json.loads(raw).get("last_eod_date") == now_et.strftime("%Y-%m-%d"):
            return False, "Închiderea și învățarea de azi sunt deja făcute."
        return True, "Fereastră activă."
    except Exception as exc:  # noqa: BLE001
        # Never break the chain because of a check error: fall back to the plain clock
        ok = now_et.weekday() < 5 and RELAY_START <= (now_et.hour, now_et.minute) < (15, 45)
        return ok, f"Verificare eșuată ({type(exc).__name__}); decizie după ceas."


def _run_session_loop(
    args: argparse.Namespace,
    *,
    state_dir: Path,
    adapter: AlpacaPaperAdapter,
    data_client: StockHistoricalDataClient,
    gemini: Any,
    sync_gh: bool,
    pull_state: Any,
) -> int:
    """Repeated 60 s cycles for `--duration-minutes N` (relay chain) or forever (`--loop`)."""
    max_duration = args.duration_minutes * 60.0 if args.duration_minutes > 0 else float("inf")
    start_time = time.time()
    lease = _EngineLease(sync_gh)
    if sync_gh:
        enable_push_dedupe(True)
    logger.info(
        "Sesiune intraday activă pornită (durată: %s min, levier: %dx, motor: %s)...",
        args.duration_minutes if args.duration_minutes > 0 else "infinit",
        args.leverage,
        lease.engine_id,
    )
    try:
        while time.time() - start_time < max_duration:
            now_utc = datetime.now(UTC)
            now_et = now_utc.astimezone(NY_TZ)
            window = live_window(now_et)
            if not window["active"]:
                if not args.loop:
                    logger.info("Sesiunea se oprește: %s", window["reason"])
                    break
                time.sleep(300)
                continue
            try:
                held, full_pull = lease.ensure()
                if held:
                    if full_pull:
                        pull_state()
                    elif sync_gh:
                        pull_state(files=(KILL_SWITCH_FILE,))  # dashboard KILL, every minute
                    if (now_et.hour, now_et.minute) < (9, 30) and _premarket_due(
                        state_dir, now_utc
                    ):
                        _run_premarket_intelligence(
                            state_dir=state_dir,
                            data_client=data_client,
                            gemini_client=gemini,
                            sync_github=sync_gh,
                            notify_telegram=True,
                        )
                        logger.info(
                            "Analiză Pre-Market actualizată (%s ET)", now_et.strftime("%H:%M")
                        )
                    if not args.loop and (now_et.hour, now_et.minute) < RELAY_START:
                        # Before 09:00 ET: briefing only, no 15-min loop (GitHub Actions minutes)
                        logger.info("Înainte de 09:00 ET: doar analiza Pre-Market, run încheiat.")
                        break
                    res = run_scheduled_cycle(
                        state_dir=state_dir,
                        adapter=adapter,
                        load_bars=lambda: _load_all_bars(data_client),
                        load_prices=lambda: _load_prices(data_client, state_dir),
                        load_opportunities=lambda: _load_opportunities(state_dir, gemini),
                        leverage=args.leverage,
                        before_step=None,
                        max_wait_min=0.0,
                        gemini_client=gemini,
                        sync_github=sync_gh,
                        github_token=settings.GH_DISPATCH_TOKEN,
                    )
                    logger.info("Ciclu intraday: status=%s", res.get("status"))
                    journal = StateStore(state_dir).read_journal()
                    if journal.get("last_eod_date") == now_et.strftime("%Y-%m-%d"):
                        logger.info("Închiderea și învățarea de azi sunt gata. Sesiune completă.")
                        if not args.loop:
                            break
                        lease.release()
                        lease.has_state = False
                        time.sleep(600)
                        continue
            except Exception as exc:  # noqa: BLE001
                logger.warning("Eroare în ciclul intraday (continuă peste 60s): %s", exc)
            remaining = max_duration - (time.time() - start_time)
            if remaining <= 10:
                break
            time.sleep(min(60, int(remaining)))
    finally:
        lease.release()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Theo Trading Bot — Sesiune Intraday Alpaca Paper")
    parser.add_argument("--auto", action="store_true", help="Rulare programată (GitHub Actions)")
    parser.add_argument(
        "--init-state",
        action="store_true",
        help="Inițializează/actualizează state/ din contul real și urcă pe branch-ul state",
    )
    parser.add_argument("--once", action="store_true", help="Un singur pas intraday, acum")
    parser.add_argument(
        "--premarket",
        action="store_true",
        help="Scanează acum pre-market-ul, știrile și raportările financiare (Finnhub + Gemini)",
    )
    parser.add_argument(
        "--weekend",
        action="store_true",
        help="Cercetare strategică weekend (retrospectivă, macro, earnings & plan Gemini)",
    )
    parser.add_argument("--eod", action="store_true", help="Închidere + învățarea zilnică, acum")
    parser.add_argument("--kill", action="store_true", help="Activează KILL și închide tot")
    parser.add_argument("--reset-kill", action="store_true", help="Dezactivează butonul KILL")
    parser.add_argument(
        "--loop",
        action="store_true",
        help="Rulează continuu în fundal (daemon local), verificând sesiunea SUA la fiecare 60s",
    )
    parser.add_argument(
        "--duration-minutes",
        type=int,
        default=0,
        help="Rulează cicluri intraday repetate timp de N minute (ex: 15 min), la fiecare 60s",
    )
    parser.add_argument("--no-sync", action="store_true", help="Nu sincroniza state/ pe GitHub")
    parser.add_argument(
        "--should-relay",
        action="store_true",
        help="Afișează yes/no: trebuie pornit următorul run de 15 min? (lanțul GitHub Actions)",
    )
    parser.add_argument(
        "--leverage",
        type=int,
        default=2,
        choices=[1, 2],
        help="Levier folosit (1 sau 2, implicit 2 conform D31)",
    )
    args = parser.parse_args()

    state_dir = ROOT / "state"
    sync_gh = not args.no_sync

    def pull_state(files: tuple[str, ...] = SYNCED_STATE_FILES) -> None:
        if sync_gh:
            res = pull_state_dir_from_github(state_dir, files=files)
            if len(files) > 1:
                logger.info("Stare restaurată din branch-ul state: %s", res)

    if args.should_relay:
        ok, reason = _should_relay()
        logger.info("Releu următor: %s — %s", "DA" if ok else "NU", reason)
        print("yes" if ok else "no")
        return 0

    trading_client = TradingClient(
        api_key=settings.ALPACA_API_KEY,
        secret_key=settings.ALPACA_SECRET_KEY,
        paper=(settings.TRADING_MODE != "LIVE"),
    )
    adapter = AlpacaPaperAdapter(trading_client, root_dir=ROOT)

    if args.reset_kill:
        pull_state()
        print(json.dumps(reset_kill_switch(state_dir=state_dir, sync_github=sync_gh), indent=2))
        return 0

    if args.kill:
        pull_state()
        res = run_kill_switch(
            state_dir=state_dir,
            adapter=adapter,
            reason="Declanșat din Dashboard / GitHub Actions (workflow kill.yml)",
            sync_github=sync_gh,
        )
        print(json.dumps(res, indent=2, ensure_ascii=False))
        return 0

    data_client = StockHistoricalDataClient(
        api_key=settings.ALPACA_API_KEY,
        secret_key=settings.ALPACA_SECRET_KEY,
    )
    gemini = _gemini_client()

    if args.premarket:
        pull_state()
        brief = _run_premarket_intelligence(
            state_dir=state_dir,
            data_client=data_client,
            gemini_client=gemini,
            sync_github=sync_gh,
            notify_telegram=True,
        )
        print(json.dumps(brief, indent=2, ensure_ascii=False))
        return 0

    if args.weekend:
        pull_state()
        brief = run_weekend_session(
            state_dir=state_dir,
            finnhub_key=settings.FINNHUB_API_KEY,
            gemini_client=gemini,
            sync_github=sync_gh,
            notify_telegram=True,
        )
        print(json.dumps(brief, indent=2, ensure_ascii=False))
        return 0

    if args.loop or args.duration_minutes > 0:
        return _run_session_loop(
            args,
            state_dir=state_dir,
            adapter=adapter,
            data_client=data_client,
            gemini=gemini,
            sync_gh=sync_gh,
            pull_state=pull_state,
        )

    if args.auto:
        now_et = datetime.now(UTC).astimezone(NY_TZ)
        if (4, 0) <= (now_et.hour, now_et.minute) < (9, 25):
            pull_state()
            brief = _run_premarket_intelligence(
                state_dir=state_dir,
                data_client=data_client,
                gemini_client=gemini,
                sync_github=sync_gh,
                notify_telegram=(now_et.hour == 8 and now_et.minute < 30),
            )
            print(
                json.dumps(
                    {"status": "premarket_updated", "premarket": brief},
                    indent=2,
                    ensure_ascii=False,
                )
            )
            return 0

        lease = _EngineLease(sync_gh)
        held, _ = lease.ensure()
        if not held:
            print(json.dumps({"status": "skipped", "reason": "alt motor are lacătul"}))
            return 0
        try:
            res = run_scheduled_cycle(
                state_dir=state_dir,
                adapter=adapter,
                load_bars=lambda: _load_all_bars(data_client),
                load_prices=lambda: _load_prices(data_client, state_dir),
                load_opportunities=lambda: _load_opportunities(state_dir, gemini),
                leverage=args.leverage,
                before_step=pull_state,
                gemini_client=gemini,
                sync_github=sync_gh,
                github_token=settings.GH_DISPATCH_TOKEN,
            )
        finally:
            lease.release()
        print(json.dumps(res, indent=2, ensure_ascii=False, default=str))
        return 0

    pull_state()
    if args.init_state:
        summary = initialize_live_paper_state(
            state_dir=state_dir,
            adapter=adapter,
            initial_capital=settings.BOT_CAPITAL,
            sync_github=sync_gh,
            github_token=settings.GH_DISPATCH_TOKEN,
            spy_price=_load_prices(data_client, state_dir).get("SPY"),
        )
        print(json.dumps(summary, indent=2, ensure_ascii=False))
        if not (args.once or args.eod):
            return 0

    lease = _EngineLease(sync_gh)
    held, _ = lease.ensure()
    if not held:
        print(json.dumps({"status": "skipped", "reason": "alt motor are lacătul"}))
        return 0
    try:
        return _run_manual_step(
            args,
            state_dir=state_dir,
            adapter=adapter,
            data_client=data_client,
            gemini=gemini,
            sync_gh=sync_gh,
        )
    finally:
        lease.release()


def _run_manual_step(
    args: argparse.Namespace,
    *,
    state_dir: Path,
    adapter: AlpacaPaperAdapter,
    data_client: StockHistoricalDataClient,
    gemini: Any,
    sync_gh: bool,
) -> int:
    """`--eod` or `--once` (one step now), run while holding the engine lease."""
    if args.eod:
        res = run_end_of_day_learning(
            state_dir=state_dir,
            adapter=adapter,
            gemini_client=gemini,
            sync_github=sync_gh,
            github_token=settings.GH_DISPATCH_TOKEN,
            prices=_load_prices(data_client, state_dir),
        )
        print(json.dumps(res, indent=2, ensure_ascii=False, default=str))
        return 0

    opps = _load_opportunities(state_dir, gemini)
    res = run_trading_step(
        state_dir=state_dir,
        adapter=adapter,
        bars_by_symbol=_load_all_bars(data_client),
        leverage=args.leverage,
        gemini_client=gemini,
        sync_github=sync_gh,
        github_token=settings.GH_DISPATCH_TOKEN,
        prices=_load_prices(data_client, state_dir),
        stock_opportunities=opps,
    )
    print(json.dumps(res, indent=2, ensure_ascii=False, default=str))
    return 0


def _main_with_alert() -> int:
    try:
        return main()
    except Exception as exc:  # noqa: BLE001
        logger.exception("Rularea sesiunii intraday a eșuat")
        try:
            from src.alerts.telegram import send_error_alert

            send_error_alert(
                component="Sesiune intraday (GitHub Actions)",
                error=f"{type(exc).__name__}: {str(exc)[:300]}",
                mode="PAPER",
            )
        except Exception:  # noqa: BLE001
            pass
        return 1


if __name__ == "__main__":
    raise SystemExit(_main_with_alert())
