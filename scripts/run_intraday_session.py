#!/usr/bin/env python3
"""CLI entrypoint for Faza B intraday paper trading on Alpaca Paper (B6c).

Modes:
  --init-state  Initialize/reset `state/` to the real 500$ Alpaca Paper account (`is_sample: False`)
                and push to the `state` branch on GitHub.
  --once        Run a single intraday evaluation cycle on SPY & QQQ and sync `state/`.
  --eod         Run end-of-day liquidation (15:59 ET), post-mortem, and daily learning.
  --kill        Trigger emergency KILL switch, liquidate all open positions, and sync `state/`.
  --loop        Run continuously during the US market session (09:30–15:59 ET), polling every 60s.
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
from alpaca.trading.client import TradingClient  # noqa: E402

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
    initialize_live_paper_state,
    run_end_of_day_learning,
    run_kill_switch,
    run_trading_step,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("intraday_session")


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


def main() -> int:
    parser = argparse.ArgumentParser(description="Theo Trading Bot — Sesiune Intraday Alpaca Paper")
    parser.add_argument(
        "--init-state",
        action="store_true",
        help="Inițializează state/ la 500$ real și urcă pe branch-ul state",
    )
    parser.add_argument(
        "--once", action="store_true", help="Rulează un singur pas de evaluare intraday"
    )
    parser.add_argument(
        "--eod", action="store_true", help="Rulează închiderea de la 15:59 ET + învățarea zilnică"
    )
    parser.add_argument(
        "--kill", action="store_true", help="Activează butonul KILL și închide toate pozițiile"
    )
    parser.add_argument(
        "--loop", action="store_true", help="Rulează în buclă la fiecare 60s în timpul sesiunii SUA"
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

    trading_client = TradingClient(
        api_key=settings.ALPACA_API_KEY,
        secret_key=settings.ALPACA_SECRET_KEY,
        paper=(settings.TRADING_MODE != "LIVE"),
    )
    adapter = AlpacaPaperAdapter(trading_client, root_dir=ROOT)

    if args.kill:
        res = run_kill_switch(
            state_dir=state_dir,
            adapter=adapter,
            reason="Declanșat din CLI / GitHub Actions (workflow kill.yml)",
            sync_github=sync_gh,
        )
        print(json.dumps(res, indent=2, ensure_ascii=False))
        return 0

    if args.init_state:
        summary = initialize_live_paper_state(
            state_dir=state_dir,
            adapter=adapter,
            initial_capital=settings.BOT_CAPITAL,
            sync_github=sync_gh,
        )
        print(json.dumps(summary, indent=2, ensure_ascii=False))
        if not (args.once or args.eod or args.loop):
            return 0

    if args.eod:
        res = run_end_of_day_learning(
            state_dir=state_dir,
            adapter=adapter,
            sync_github=sync_gh,
        )
        print(json.dumps(res, indent=2, ensure_ascii=False, default=str))
        return 0

    data_client = StockHistoricalDataClient(
        api_key=settings.ALPACA_API_KEY,
        secret_key=settings.ALPACA_SECRET_KEY,
    )

    if args.once or not args.loop:
        bars_by_sym = {sym: _load_recent_bars(data_client, sym) for sym in ("SPY", "QQQ")}
        res = run_trading_step(
            state_dir=state_dir,
            adapter=adapter,
            bars_by_symbol=bars_by_sym,
            leverage=args.leverage,
            sync_github=sync_gh,
        )
        print(json.dumps(res, indent=2, ensure_ascii=False, default=str))
        return 0

    logger.info("Pornire buclă intraday (SPY/QQQ, Long+Short, levier %dx)...", args.leverage)
    eod_done_date: str | None = None
    while True:
        now_et = datetime.now(UTC).astimezone(NY_TZ)
        today_str = now_et.strftime("%Y-%m-%d")
        hhmm = (now_et.hour, now_et.minute)

        if hhmm >= (15, 59) and eod_done_date != today_str:
            logger.info("15:59 ET atins — rulare lichidare EOD + învățare zilnică...")
            run_end_of_day_learning(
                state_dir=state_dir,
                adapter=adapter,
                sync_github=sync_gh,
            )
            eod_done_date = today_str
            break

        if (9, 30) <= hhmm < (15, 59):
            bars_by_sym = {sym: _load_recent_bars(data_client, sym) for sym in ("SPY", "QQQ")}
            step_res = run_trading_step(
                state_dir=state_dir,
                adapter=adapter,
                bars_by_symbol=bars_by_sym,
                leverage=args.leverage,
                sync_github=sync_gh,
            )
            logger.info(
                "Pas intraday executat: status=%s, ordine=%d",
                step_res["status"],
                len(step_res["orders"]),
            )
            if step_res["status"] in ("halted", "killed"):
                break
        else:
            logger.info(
                "În afara orelor de tranzacționare (%s ET) — sincronizare stare cont...",
                now_et.strftime("%H:%M"),
            )
            initialize_live_paper_state(
                state_dir=state_dir,
                adapter=adapter,
                initial_capital=settings.BOT_CAPITAL,
                sync_github=sync_gh,
            )

        time.sleep(60)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
