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
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from alpaca.data.historical import StockHistoricalDataClient  # noqa: E402
from alpaca.data.requests import StockLatestTradeRequest  # noqa: E402
from alpaca.trading.client import TradingClient  # noqa: E402

from src.broker.alpaca_paper import AlpacaPaperAdapter  # noqa: E402
from src.config import settings  # noqa: E402
from src.data.intraday import (  # noqa: E402
    fetch_minute_bars,
    filter_regular_session,
    load_minute_bars,
    nyse_sessions,
)
from src.live.runner import (  # noqa: E402
    initialize_live_paper_state,
    reset_kill_switch,
    run_end_of_day_learning,
    run_kill_switch,
    run_scheduled_cycle,
    run_trading_step,
)
from src.live.state_writer import pull_state_dir_from_github  # noqa: E402
from src.risk.guard import ALLOWED_SYMBOLS  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("intraday_session")

SIGNAL_SYMBOLS = ("SPY", "QQQ")


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


def _load_prices(data_client: StockHistoricalDataClient) -> dict[str, float]:
    """Latest IEX trade price for every allowed ETF (needed to price SH/SDS/SSO/... orders)."""
    syms = sorted(ALLOWED_SYMBOLS)
    try:
        latest = data_client.get_stock_latest_trade(
            StockLatestTradeRequest(symbol_or_symbols=syms, feed="iex")
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Nu s-au putut citi prețurile curente: %s", exc)
        return {}
    return {s: float(latest[s].price) for s in syms if s in latest and latest[s].price}


def _gemini_client():
    if not settings.GEMINI_API_KEY:
        return None
    try:
        from google import genai

        return genai.Client(api_key=settings.GEMINI_API_KEY)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Clientul Gemini nu a putut fi creat: %s", type(exc).__name__)
        return None


def main() -> int:
    parser = argparse.ArgumentParser(description="Theo Trading Bot — Sesiune Intraday Alpaca Paper")
    parser.add_argument("--auto", action="store_true", help="Rulare programată (GitHub Actions)")
    parser.add_argument(
        "--init-state",
        action="store_true",
        help="Inițializează/actualizează state/ din contul real și urcă pe branch-ul state",
    )
    parser.add_argument("--once", action="store_true", help="Un singur pas intraday, acum")
    parser.add_argument("--eod", action="store_true", help="Închidere + învățarea zilnică, acum")
    parser.add_argument("--kill", action="store_true", help="Activează KILL și închide tot")
    parser.add_argument("--reset-kill", action="store_true", help="Dezactivează butonul KILL")
    parser.add_argument(
        "--loop",
        action="store_true",
        help="Rulează continuu în fundal (daemon local), verificând sesiunea SUA la fiecare 60s",
    )
    parser.add_argument("--no-sync", action="store_true", help="Nu sincroniza state/ pe GitHub")
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

    def pull_state() -> None:
        if sync_gh:
            res = pull_state_dir_from_github(state_dir)
            logger.info("Stare restaurată din branch-ul state: %s", res)

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

    if args.loop:
        logger.info("Daemon intraday pornit (--loop, levier %dx)...", args.leverage)
        while True:
            try:
                res = run_scheduled_cycle(
                    state_dir=state_dir,
                    adapter=adapter,
                    load_bars=lambda: _load_all_bars(data_client),
                    load_prices=lambda: _load_prices(data_client),
                    leverage=args.leverage,
                    before_step=pull_state,
                    gemini_client=gemini,
                    sync_github=sync_gh,
                )
                logger.info("Ciclu intraday: status=%s", res.get("status"))
            except Exception as exc:  # noqa: BLE001
                logger.warning("Eroare în ciclul --loop (continuă peste 60s): %s", exc)
            time.sleep(60)

    if args.auto:
        res = run_scheduled_cycle(
            state_dir=state_dir,
            adapter=adapter,
            load_bars=lambda: _load_all_bars(data_client),
            load_prices=lambda: _load_prices(data_client),
            leverage=args.leverage,
            before_step=pull_state,
            gemini_client=gemini,
            sync_github=sync_gh,
        )
        print(json.dumps(res, indent=2, ensure_ascii=False, default=str))
        return 0

    pull_state()
    if args.init_state:
        summary = initialize_live_paper_state(
            state_dir=state_dir,
            adapter=adapter,
            initial_capital=settings.BOT_CAPITAL,
            sync_github=sync_gh,
            spy_price=_load_prices(data_client).get("SPY"),
        )
        print(json.dumps(summary, indent=2, ensure_ascii=False))
        if not (args.once or args.eod):
            return 0

    if args.eod:
        res = run_end_of_day_learning(
            state_dir=state_dir,
            adapter=adapter,
            gemini_client=gemini,
            sync_github=sync_gh,
            prices=_load_prices(data_client),
        )
        print(json.dumps(res, indent=2, ensure_ascii=False, default=str))
        return 0

    res = run_trading_step(
        state_dir=state_dir,
        adapter=adapter,
        bars_by_symbol=_load_all_bars(data_client),
        leverage=args.leverage,
        gemini_client=gemini,
        sync_github=sync_gh,
        prices=_load_prices(data_client),
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
