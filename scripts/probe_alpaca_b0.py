"""Sub-pasul B0: verifică, doar prin citire, ce oferă Alpaca pentru Faza B.

1. De la ce dată există bare de 1 minut SPY/QQQ pe planul gratuit (feed SIP și IEX).
2. Dacă contul paper permite short pe SPY/QQQ și cu ce marjă.

Nu plasează niciun ordin. Rezultatul se scrie în .cache/probe_alpaca_b0.json.
Rulare: PYTHONPATH=. uv run python scripts/probe_alpaca_b0.py
"""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from alpaca.data.enums import Adjustment, DataFeed
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame
from alpaca.trading.client import TradingClient

from src.config import settings

SYMBOLS = ["SPY", "QQQ"]
FEEDS = [DataFeed.SIP, DataFeed.IEX]
FAR_START = datetime(2000, 1, 1, tzinfo=UTC)
# Zile de probă pentru numărul de bare dintr-o sesiune completă (390 = 9:30-16:00 ET)
SAMPLE_DAYS = ["2015-03-03", "2016-03-01", "2020-03-03", "2025-03-04"]
OUT = Path(__file__).resolve().parent.parent / ".cache" / "probe_alpaca_b0.json"


def _bars(client, symbol, feed, start, end, limit=None):
    req = StockBarsRequest(
        symbol_or_symbols=symbol,
        timeframe=TimeFrame.Minute,
        start=start,
        end=end,
        feed=feed,
        adjustment=Adjustment.RAW,
        limit=limit,
    )
    return client.get_stock_bars(req).data.get(symbol, [])


def probe_data(client):
    result = {}
    now = datetime.now(UTC)
    for feed in FEEDS:
        for symbol in SYMBOLS:
            key = f"{symbol}_{feed.value}"
            entry = {}
            try:
                first = _bars(client, symbol, feed, FAR_START, now - timedelta(days=1), limit=1)
                entry["first_bar"] = first[0].timestamp.isoformat() if first else None
            except Exception as exc:  # noqa: BLE001
                entry["first_bar_error"] = str(exc)[:200]
            counts = {}
            for day in SAMPLE_DAYS:
                # Zilele de probă sunt în ora de iarnă: 9:30 ET = 14:30 UTC
                start = datetime.fromisoformat(day).replace(hour=14, minute=30, tzinfo=UTC)
                end = start + timedelta(hours=6.5)
                try:
                    counts[day] = len(_bars(client, symbol, feed, start, end))
                except Exception as exc:  # noqa: BLE001
                    counts[day] = f"error: {str(exc)[:120]}"
            entry["bars_in_session"] = counts
            # Planul gratuit nu permite SIP în ultimele 15 minute
            try:
                recent = _bars(client, symbol, feed, now - timedelta(minutes=10), now)
                entry["last_10_min"] = f"ok ({len(recent)} bare)"
            except Exception as exc:  # noqa: BLE001
                entry["last_10_min"] = f"error: {str(exc)[:160]}"
            result[key] = entry
    return result


def probe_account(trading):
    acc = trading.get_account()
    cfg = trading.get_account_configurations()
    fields = [
        "status",
        "trading_blocked",
        "account_blocked",
        "shorting_enabled",
        "multiplier",
        "equity",
        "cash",
        "buying_power",
        "daytrading_buying_power",
        "regt_buying_power",
        "non_marginable_buying_power",
        "pattern_day_trader",
        "daytrade_count",
    ]
    out = {"account": {f: str(getattr(acc, f, None)) for f in fields}}
    out["configuration"] = {k: str(v) for k, v in cfg.model_dump().items()}
    assets = {}
    for symbol in SYMBOLS:
        asset = trading.get_asset(symbol)
        assets[symbol] = {
            k: str(v)
            for k, v in asset.model_dump().items()
            if k
            in {
                "tradable",
                "shortable",
                "easy_to_borrow",
                "marginable",
                "fractionable",
                "maintenance_margin_requirement",
                "margin_requirement_long",
                "margin_requirement_short",
            }
        }
    out["assets"] = assets
    return out


def main():
    data_client = StockHistoricalDataClient(settings.ALPACA_API_KEY, settings.ALPACA_SECRET_KEY)
    trading = TradingClient(settings.ALPACA_API_KEY, settings.ALPACA_SECRET_KEY, paper=True)
    report = {
        "run_at": datetime.now(UTC).isoformat(),
        "data": probe_data(data_client),
        "paper": probe_account(trading),
    }
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(report, indent=2, ensure_ascii=False))
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
