"""Market-wide stock mover & news catalyst scanner for opportunistic trading (Faza B, D33).

Scans across the entire US market (Alpaca top movers/gainers/losers, Finnhub earnings & news
tickers, and a 60+ high-activity stock universe across large/mid/small-cap stocks).
Identifies stocks with strong Pre-Market or intraday movement + news/financial report catalysts,
computes dynamic Risk:Reward setups (1:3 to 1:10) with small capital allocations (5$–40$ per
trade out of the 500$ account), and feeds them to the live execution engine and Dashboard.
"""

from __future__ import annotations

import json
import logging
import re
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import requests

from src.ai.veto import CRISIS_KEYWORDS, fetch_recent_news
from src.config import settings
from src.state.store import StateStore

logger = logging.getLogger(__name__)

ALPACA_MOVERS_URL = "https://data.alpaca.markets/v1beta1/screener/stocks/movers"
ALPACA_SNAPSHOTS_URL = "https://data.alpaca.markets/v2/stocks/snapshots"
ALPACA_PAPER_ASSETS_URL = "https://paper-api.alpaca.markets/v2/assets"
ALPACA_LIVE_ASSETS_URL = "https://api.alpaca.markets/v2/assets"
TICKER_RE = re.compile(r"^[A-Z]{1,5}$")

# Safety filters for scanner trades (B6f)
MIN_MOVER_PRICE = 2.0  # D36 (owner): 2-5 $ runners (GOGO, QNTU, FLYT) won on 6.11.2026
MAX_AI_EVALS_PER_SCAN = 6  # at most this many Gemini calls per scan (free-tier rate limit)
AI_CALL_SPACING_S = 4.5  # >= 4.5 s between Gemini calls -> <= ~13 requests per minute
# Leveraged / inverse products are never traded as "movers" (AGENTS.md: leverage 1x/2x only, and
# a 2x short ETF bought as a "gainer" would be a hidden leveraged short).
LEVERAGED_NAME_RE = re.compile(
    r"(\b[1-9](\.\d)?x\b|-[1-9]x|\bultra|\bleveraged\b|\binverse\b|\bbear\b|\bbull\b|"
    r"\bshort\b|daily target|\bdirexion\b|\bproshares\b|\bdefiance daily\b)",
    re.IGNORECASE,
)
_ASSET_CACHE: dict[str, dict[str, Any] | None] = {}

# Broad active watchlist across Mega-Cap, Semiconductors, AI/Cloud, Fintech, Biotech, EV, Energy
ACTIVE_SCAN_UNIVERSE: tuple[str, ...] = (
    "SPY",
    "QQQ",
    "NVDA",
    "TSLA",
    "AMD",
    "INTC",
    "AAPL",
    "MSFT",
    "AMZN",
    "META",
    "GOOGL",
    "NFLX",
    "AVGO",
    "PLTR",
    "SOFI",
    "COIN",
    "MARA",
    "RIOT",
    "SMCI",
    "MU",
    "ARM",
    "MRVL",
    "QCOM",
    "TSM",
    "ASML",
    "CRM",
    "ORCL",
    "SNOW",
    "PANW",
    "CRWD",
    "SHOP",
    "UBER",
    "ABNB",
    "PYPL",
    "SQ",
    "AFRM",
    "UPST",
    "HOOD",
    "RBLX",
    "U",
    "RIVN",
    "LCID",
    "NIO",
    "BA",
    "CAT",
    "GE",
    "JPM",
    "BAC",
    "GS",
    "XOM",
    "CVX",
    "LLY",
    "UNH",
    "PFE",
    "MRNA",
    "DIS",
    "NKE",
    "COST",
    "WMT",
    "TGT",
    "IONQ",
    "RKLB",
)

# Inverse ETF mapping for shorting individual stocks on a < 2000$ cash/paper account (D31/D33)
# Only dedicated single-stock inverse ETFs (B6f): a short on any other stock is skipped. The old
# fallbacks (QID for "everything else", SOXS -3x for semiconductors) bought instruments that do
# not follow the shorted stock, and SOXS breaks the 1x/2x leverage rule.
SINGLE_STOCK_INVERSE_MAP: dict[str, str] = {
    "NVDA": "NVD",
    "TSLA": "TSLS",
    "AAPL": "AAPD",
    "MSFT": "MSFD",
    "AMZN": "AMZD",
    "META": "METD",
    "GOOGL": "GGLS",
    "GOOG": "GGLS",
    "COIN": "CONI",
}
# Daily leverage of each proxy (-1x unless listed); used to translate the stop distance.
PROXY_LEVERAGE: dict[str, int] = {"NVD": 2, "CONI": 2}


def is_valid_stock_symbol(symbol: str) -> bool:
    """Return True if `symbol` is a standard US equity/ETF ticker (excludes 5-letter specials)."""
    sym = str(symbol or "").strip().upper()
    if not TICKER_RE.match(sym):
        return False
    # Exclude 5-letter NASDAQ Warrants (W), Rights (R), Units (U), Stubs (Z) like RGTIW, and
    # Q = company in bankruptcy proceedings
    if len(sym) == 5 and sym[-1] in ("W", "R", "U", "Z", "Q"):
        return False
    return True


def fetch_asset_profile(
    symbol: str,
    api_key: str | None = None,
    secret_key: str | None = None,
    session: Any = None,
) -> dict[str, Any] | None:
    """Alpaca asset record (`status`, `tradable`, `fractionable`, `exchange`, `name`), cached."""
    sym = str(symbol or "").upper().strip()
    if sym in _ASSET_CACHE:
        return _ASSET_CACHE[sym]
    key = (api_key if api_key is not None else settings.ALPACA_API_KEY).strip()
    sec = (secret_key if secret_key is not None else settings.ALPACA_SECRET_KEY).strip()
    if not key or not sec or not sym:
        return None
    base = ALPACA_LIVE_ASSETS_URL if settings.TRADING_MODE == "LIVE" else ALPACA_PAPER_ASSETS_URL
    http = session or requests
    try:
        resp = http.get(
            f"{base}/{sym}",
            headers={"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": sec},
            timeout=5.0,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Activul %s nu a putut fi verificat: %s", sym, type(exc).__name__)
        return None  # not cached: retried at the next scan
    status = getattr(resp, "status_code", 500)
    if status == 404:
        _ASSET_CACHE[sym] = None
        return None
    if status != 200:
        return None
    try:
        payload = resp.json()
    except Exception:  # noqa: BLE001
        return None
    profile = payload if isinstance(payload, dict) else None
    _ASSET_CACHE[sym] = profile
    return profile


def check_tradable_asset(
    asset: dict[str, Any] | None, price: float | None = None
) -> tuple[bool, str]:
    """Fail-closed eligibility of a mover: active, tradable, fractionable (or whole-share <= 35$),
    exchange-listed and not a leveraged/inverse product."""
    if not asset:
        return False, "activul nu a putut fi verificat la Alpaca"
    if str(asset.get("status", "")).lower() != "active" or not asset.get("tradable"):
        return False, "activul nu este tranzacționabil pe Alpaca"
    if not asset.get("fractionable") and (price is None or price > 35.0):
        return False, "activul nu acceptă fracțiuni (mizele de 5–35 $ nu încap)"
    if str(asset.get("exchange", "")).upper() in ("OTC", "CRYPTO"):
        return False, "activul nu este listat pe o bursă SUA"
    if LEVERAGED_NAME_RE.search(str(asset.get("name", ""))):
        return False, "ETF cu levier / invers (interzis ca oportunitate)"
    return True, ""


def _load_learning_context(state_dir: Path | None) -> tuple[list[str], str]:
    """Load recent autopsy lessons and weekend tactical plan from `state/` for AI evaluation."""
    if state_dir is None:
        return [], ""
    try:
        store = StateStore(state_dir)
        lessons: list[str] = []
        for a in store.read_autopsies()[-6:]:
            les = str(a.get("lesson") or a.get("lesson_ro") or "").strip()
            if les and les not in lessons:
                lessons.append(les)
        stats_lessons = store.read_learning_stats().get("last_lessons") or []
        for les in stats_lessons:
            s = str(les).strip()
            if s and s not in lessons:
                lessons.append(s)

        summary = store.read_summary()
        wb = summary.get("weekend_briefing") or {}
        for les in wb.get("lessons_learned") or []:
            s = str(les).strip()
            if s and s not in lessons:
                lessons.append(s)
        tactical = str(wb.get("tactical_plan_ro") or "").strip()
        return lessons[-5:], tactical
    except Exception:  # noqa: BLE001
        return [], ""


def resolve_short_proxy_symbol(symbol: str) -> str | None:
    """Dedicated inverse ETF expressing a SHORT on `symbol` (< 2000 $ account), or None."""
    return SINGLE_STOCK_INVERSE_MAP.get(symbol.upper().strip())


def fetch_alpaca_top_movers(
    api_key: str | None = None,
    secret_key: str | None = None,
    session: Any = None,
    top: int = 20,
) -> list[dict[str, Any]]:
    """Fetch market-wide top percentage gainers and losers across all US stocks from Alpaca."""
    key = (api_key if api_key is not None else settings.ALPACA_API_KEY).strip()
    sec = (secret_key if secret_key is not None else settings.ALPACA_SECRET_KEY).strip()
    if not key or not sec:
        return []

    http = session or requests
    headers = {"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": sec}
    try:
        resp = http.get(
            ALPACA_MOVERS_URL,
            headers=headers,
            params={"top": top},
            timeout=5.0,
        )
        if getattr(resp, "status_code", 500) != 200:
            return []
        payload = resp.json()
        if not isinstance(payload, dict):
            return []
        raw_list = (payload.get("gainers") or []) + (payload.get("losers") or [])
        out: list[dict[str, Any]] = []
        for item in raw_list:
            if not isinstance(item, dict):
                continue
            sym = str(item.get("symbol") or "").upper().strip()
            if not is_valid_stock_symbol(sym):
                continue
            price = float(item.get("price") or 0.0)
            chg_pct = float(item.get("percent_change") or 0.0)
            # Filter out low-priced runners (wide spreads, thin IEX quotes)
            if price < MIN_MOVER_PRICE:
                continue
            prev_close = price / (1.0 + chg_pct / 100.0) if (100.0 + chg_pct) > 1e-3 else price
            out.append(
                {
                    "symbol": sym,
                    "price": round(price, 2),
                    "prev_close": round(prev_close, 2),
                    "gap_pct": round(chg_pct, 2),
                    "source": "alpaca_movers",
                }
            )
        return out
    except Exception as exc:  # noqa: BLE001
        logger.warning("Eroare la citirea Alpaca top movers: %s", type(exc).__name__)
        return []


def fetch_watchlist_snapshots(
    symbols: list[str] | tuple[str, ...] = ACTIVE_SCAN_UNIVERSE,
    api_key: str | None = None,
    secret_key: str | None = None,
    session: Any = None,
) -> dict[str, dict[str, Any]]:
    """Fetch real-time pre-market / intraday snapshots for a list of symbols via Alpaca."""
    key = (api_key if api_key is not None else settings.ALPACA_API_KEY).strip()
    sec = (secret_key if secret_key is not None else settings.ALPACA_SECRET_KEY).strip()
    clean_syms = [s.upper().strip() for s in symbols if is_valid_stock_symbol(s)]
    if not key or not sec or not clean_syms:
        return {}

    http = session or requests
    headers = {"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": sec}
    out: dict[str, dict[str, Any]] = {}
    # Query in chunks of 40 symbols
    for i in range(0, len(clean_syms), 40):
        batch = clean_syms[i : i + 40]
        try:
            resp = http.get(
                ALPACA_SNAPSHOTS_URL,
                headers=headers,
                params={"symbols": ",".join(batch), "feed": "iex"},
                timeout=6.0,
            )
            if getattr(resp, "status_code", 500) != 200:
                continue
            data = resp.json()
            if not isinstance(data, dict):
                continue
            for sym, snap in data.items():
                if not isinstance(snap, dict):
                    continue
                latest_trade = snap.get("latestTrade") or {}
                minute_bar = snap.get("minuteBar") or {}
                daily_bar = snap.get("dailyBar") or {}
                prev_daily = snap.get("prevDailyBar") or {}

                price = float(
                    latest_trade.get("p") or minute_bar.get("c") or daily_bar.get("c") or 0.0
                )
                prev_close = float(prev_daily.get("c") or daily_bar.get("o") or price)
                if price <= 0 or prev_close <= 0:
                    continue
                gap_pct = (price - prev_close) / prev_close * 100.0
                out[sym.upper()] = {
                    "symbol": sym.upper(),
                    "price": round(price, 2),
                    "prev_close": round(prev_close, 2),
                    "gap_pct": round(gap_pct, 2),
                    "source": "watchlist_snapshot",
                }
        except Exception as exc:  # noqa: BLE001
            logger.warning("Eroare la citirea snapshot-urilor Alpaca: %s", type(exc).__name__)
    return out


def discover_market_movers(
    *,
    extra_symbols: list[str] | None = None,
    api_key: str | None = None,
    secret_key: str | None = None,
    session: Any = None,
    max_candidates: int = 12,
) -> list[dict[str, Any]]:
    """Combine market-wide Alpaca gainers/losers + watchlist snapshots + earnings tickers."""
    combined_watchlist = list(ACTIVE_SCAN_UNIVERSE)
    for s in extra_symbols or []:
        su = str(s).upper().strip()
        if is_valid_stock_symbol(su) and su not in combined_watchlist:
            combined_watchlist.append(su)

    by_sym = fetch_watchlist_snapshots(
        combined_watchlist, api_key=api_key, secret_key=secret_key, session=session
    )
    movers = fetch_alpaca_top_movers(
        api_key=api_key, secret_key=secret_key, session=session, top=20
    )
    for m in movers:
        sym = m["symbol"]
        if sym not in by_sym or abs(m["gap_pct"]) > abs(by_sym[sym]["gap_pct"]):
            by_sym[sym] = m

    ranked = sorted(by_sym.values(), key=lambda x: abs(float(x.get("gap_pct", 0.0))), reverse=True)
    return ranked[:max_candidates]


def evaluate_mover_opportunity(
    mover: dict[str, Any],
    *,
    headlines: list[str] | None = None,
    finnhub_key: str | None = None,
    gemini_client: Any = None,
    session: Any = None,
    min_abs_gap_pct: float = 1.2,
    default_stake_dollars: float = 15.0,
    lessons_context: list[str] | None = None,
    tactical_context: str | None = None,
    api_key: str | None = None,
    secret_key: str | None = None,
    check_asset: bool = True,
) -> dict[str, Any]:
    """Analyze a single stock mover (pre-market or intraday) and build a Risk:Reward trade plan.

    Fail-closed (B6f): without a valid Gemini confirmation (no client, HTTP 429, bad JSON,
    `enter` not explicitly true) the mover stays on the watch list and is never traded.

    Returns a dictionary with:
    - `action`: `"enter"` or `"watch"`
    - `symbol`, `direction` (`"long"` / `"short"`), `price`, `gap_pct`
    - `stake_dollars` (5$ – 40$), `rr_ratio` (3.0 – 10.0), `stop_price`, `target_price`
    - `reason_ro`: clear Romanian explanation of the catalyst and R:R calculation.
    """
    sym = str(mover.get("symbol") or "").upper()
    price = float(mover.get("price") or 0.0)
    prev_close = float(mover.get("prev_close") or price)
    gap_pct = float(mover.get("gap_pct") or 0.0)

    if price <= 0 or abs(gap_pct) < min_abs_gap_pct or not is_valid_stock_symbol(sym):
        return {
            "action": "watch",
            "symbol": sym,
            "price": price,
            "gap_pct": gap_pct,
            "reason_ro": f"Mișcare {gap_pct:+.2f}% sub pragul minim de {min_abs_gap_pct:.1f}%.",
        }

    def _watch(reason: str, **extra: Any) -> dict[str, Any]:
        return {
            "action": "watch",
            "symbol": sym,
            "price": price,
            "gap_pct": gap_pct,
            "reason_ro": reason,
            **extra,
        }

    if price < MIN_MOVER_PRICE:
        return _watch(f"Preț {price:.2f} $ sub minimul de {MIN_MOVER_PRICE:.0f} $ (spread mare).")
    asset_profile: dict[str, Any] | None = None
    if check_asset:
        asset_profile = fetch_asset_profile(
            sym, api_key=api_key, secret_key=secret_key, session=session
        )
        ok, why = check_tradable_asset(asset_profile, price=price)
        if not ok:
            return _watch(f"Exclus: {why}.")

    if headlines is None:
        news_items = fetch_recent_news(
            sym, finnhub_key=finnhub_key, session=session, lookback_hours=18
        )
        headlines = [
            str(it.get("headline") or "").strip() for it in news_items if it.get("headline")
        ]

    clean_headlines = [h for h in (headlines or []) if h]
    joined_lower = " | ".join(clean_headlines).lower()
    for kw in CRISIS_KEYWORDS:
        if kw in joined_lower:
            return {
                "action": "watch",
                "symbol": sym,
                "price": price,
                "gap_pct": gap_pct,
                "reason_ro": f"Blocat: alertă de oprire/criză pe {sym} ('{kw}').",
            }

    # Mechanical baseline direction, stop %, R:R ratio (1:3 to 1:8), and stake (10$ - 25$)
    direction = "long" if gap_pct > 0 else "short"
    abs_move = abs(gap_pct)
    stop_pct = min(0.025, max(0.008, (abs_move / 100.0) * 0.30))
    if abs_move >= 10.0:
        rr_ratio = 6.0
        stake_dollars = 20.0
    elif abs_move >= 5.0:
        rr_ratio = 4.5
        stake_dollars = 15.0
    else:
        rr_ratio = 3.5
        stake_dollars = default_stake_dollars

    top_news = clean_headlines[0] if clean_headlines else "volum și impuls puternic în Pre-Market"
    dir_ro = "crescut" if gap_pct > 0 else "scăzut"
    catalyst_ro = (
        f"{sym} a {dir_ro} cu {gap_pct:+.2f}% (preț {price:.2f} $ vs {prev_close:.2f} $) "
        f"pe fondul: {top_news[:140]}."
    )

    if gemini_client is None:
        return _watch("Fără analiza AI (Gemini indisponibil): doar urmărire, nicio intrare.")

    from zoneinfo import ZoneInfo

    now_et = datetime.now(UTC).astimezone(ZoneInfo("America/New_York"))
    is_regular_open = (9, 45) <= (now_et.hour, now_et.minute) < (16, 0)
    session_note = (
        f"Ora curentă NY: {now_et.strftime('%H:%M')} ET — sesiunea principală NYSE este DESCHISĂ "
        "(am trecut de primele 15 minute de la deschidere; NU mai suntem în pre-market).\n"
        if is_regular_open
        else f"Ora curentă NY: {now_et.strftime('%H:%M')} ET.\n"
    )
    lessons_block = ""
    if lessons_context:
        lessons_block = (
            "\nLecții din tranzacțiile anterioare (aplică-le doar când sunt relevante):\n- "
            + "\n- ".join(lessons_context[:5])
            + "\n"
        )
    tactical_block = f"\nContext săptămânal: {tactical_context}\n" if tactical_context else ""
    prompt = (
        "Ești analistul de oportunități intraday al botului Theo Trading Bot (cont 500 $).\n"
        + session_note
        + f"Acțiunea {sym} are prețul {price:.2f} $ "
        f"(mișcare {gap_pct:+.2f}% față de închiderea {prev_close:.2f} $).\n"
        "Știri recente despre companie:\n- "
        + (
            "\n- ".join(clean_headlines[:5])
            if clean_headlines
            else "Fără știri directe; mișcare tehnică puternică de volum în sesiunea activă."
        )
        + lessons_block
        + tactical_block
        + "\n\nRăspunde DOAR în JSON valid:\n"
        '`{"enter": true/false, "direction": "long"|"short", "rr_ratio": 3.0..10.0, '
        '"stake_dollars": 5.0..35.0, "stop_pct": 0.008..0.03, '
        '"catalyst_ro": "1-2 fraze în română"}`\n'
        "Reguli: aprobă intrarea (`enter: true`) dacă acțiunea are un catalizator clar "
        "(știre pozitivă/negativă, contract, achiziție, raport financiar, upgrade/downgrade) "
        "sau un trend intraday puternic. IMPORTANT: dacă sesiunea NYSE este deja deschisă "
        "(după 09:45 ET), NU respinge acțiunea invocând 'pre-market' sau 'primele 15 minute' — "
        "respinge (`enter: false`) DOAR dacă știrea este o capcană clară (ex: diluție/offering de "
        "acțiuni, faliment) sau direcția e incertă. "
        "Alege raportul Risc:Reward (`rr_ratio` între 3 și 10) și miza (`stake_dollars` "
        "între 5$ și 35$) proporțional cu claritatea catalizatorului."
    )
    try:
        model_name = settings.GEMINI_MODEL
        if model_name == "gemini-2.5-flash-lite":
            model_name = "gemini-flash-lite-latest"
        resp = gemini_client.models.generate_content(model=model_name, contents=prompt)
        raw = (getattr(resp, "text", None) or "").strip()
        if raw.startswith("```"):
            raw = raw.strip("`").removeprefix("json").strip()
        parsed = json.loads(raw)
        if not isinstance(parsed, dict):
            raise ValueError("răspuns AI fără obiect JSON")
    except Exception as exc:  # noqa: BLE001
        logger.warning("Gemini indisponibil pentru %s (%s): fără intrare", sym, type(exc).__name__)
        return _watch(
            f"Analiza AI a eșuat ({type(exc).__name__}): nicio intrare fără confirmare.",
            _ai_called=True,
        )

    if parsed.get("enter") is not True:
        return _watch(str(parsed.get("catalyst_ro") or "Filtrat de analiza AI."), _ai_called=True)
    try:
        cand_dir = str(parsed.get("direction") or direction).lower().strip()
        if cand_dir in ("long", "short"):
            direction = cand_dir
        rr_ratio = float(min(10.0, max(3.0, float(parsed.get("rr_ratio") or rr_ratio))))
        stake_dollars = float(
            min(35.0, max(5.0, float(parsed.get("stake_dollars") or stake_dollars)))
        )
        stop_pct = float(min(0.03, max(0.008, float(parsed.get("stop_pct") or stop_pct))))
    except (TypeError, ValueError):
        return _watch("Răspuns AI invalid (valori nenumerice): nicio intrare.", _ai_called=True)
    ai_cat = str(parsed.get("catalyst_ro") or "").strip()
    if ai_cat:
        catalyst_ro = ai_cat

    target_pct = stop_pct * rr_ratio
    if direction == "long":
        stop_price = round(price * (1.0 - stop_pct), 2)
        target_price = round(price * (1.0 + target_pct), 2)
    else:
        stop_price = round(price * (1.0 + stop_pct), 2)
        target_price = round(price * (1.0 - target_pct), 2)

    expected_profit = round((stake_dollars * target_pct), 2)
    max_loss = round((stake_dollars * stop_pct), 2)
    reason_ro = (
        f"{catalyst_ro} Intrare {direction.upper()} cu miză {stake_dollars:.0f} $, "
        f"Risc:Reward 1:{rr_ratio:.1f} "
        f"(risc -{max_loss:.2f} $ / țintă profit +{expected_profit:.2f} $)."
    )

    return {
        "action": "enter",
        "symbol": sym,
        "direction": direction,
        "price": round(price, 2),
        "prev_close": round(prev_close, 2),
        "gap_pct": round(gap_pct, 2),
        "change_pct": round(gap_pct, 2),
        "stake_dollars": round(stake_dollars, 2),
        "rr_ratio": round(rr_ratio, 1),
        "stop_pct": round(stop_pct, 4),
        "target_pct": round(target_pct, 4),
        "stop_price": stop_price,
        "target_price": target_price,
        "expected_profit_dollars": expected_profit,
        "max_loss_dollars": max_loss,
        "headlines": clean_headlines[:3],
        "reason_ro": reason_ro,
        "fractionable": bool(asset_profile.get("fractionable", True)) if asset_profile else True,
        "evaluated_at": datetime.now(UTC).isoformat(),
        "_ai_called": True,
    }


def scan_market_opportunities(
    *,
    extra_symbols: list[str] | None = None,
    api_key: str | None = None,
    secret_key: str | None = None,
    finnhub_key: str | None = None,
    gemini_client: Any = None,
    session: Any = None,
    min_abs_gap_pct: float = 1.2,
    max_opportunities: int = 6,
    state_dir: Path | None = None,
    max_ai_evals: int = MAX_AI_EVALS_PER_SCAN,
    ai_spacing_s: float = AI_CALL_SPACING_S,
    sleep_fn: Any = time.sleep,
) -> dict[str, Any]:
    """Scan the US market for top movers and return ranked trade opportunities + watchlist.

    At most `max_ai_evals` Gemini calls per scan, spaced by `ai_spacing_s` (free-tier limit).
    """
    movers = discover_market_movers(
        extra_symbols=extra_symbols,
        api_key=api_key,
        secret_key=secret_key,
        session=session,
        max_candidates=14,
    )
    lessons_ctx, tactical_ctx = _load_learning_context(state_dir)
    opportunities: list[dict[str, Any]] = []
    watched: list[dict[str, Any]] = []
    ai_calls = 0
    last_ai_called = False

    for m in movers:
        if m["symbol"] in ("SPY", "QQQ"):
            continue
        if len(opportunities) >= max_opportunities or ai_calls >= max_ai_evals:
            watched.append(
                {
                    "action": "watch",
                    "symbol": m["symbol"],
                    "price": m["price"],
                    "gap_pct": m["gap_pct"],
                    "reason_ro": f"Pe lista de urmărire ({m['gap_pct']:+.2f}%).",
                }
            )
            continue
        if last_ai_called:
            sleep_fn(ai_spacing_s)
        ev = evaluate_mover_opportunity(
            m,
            finnhub_key=finnhub_key,
            gemini_client=gemini_client,
            session=session,
            min_abs_gap_pct=min_abs_gap_pct,
            lessons_context=lessons_ctx,
            tactical_context=tactical_ctx,
            api_key=api_key,
            secret_key=secret_key,
        )
        last_ai_called = bool(ev.pop("_ai_called", False))
        if last_ai_called:
            ai_calls += 1
        if ev.get("action") == "enter":
            opportunities.append(ev)
        else:
            watched.append(ev)

    return {
        "scanned_at": datetime.now(UTC).isoformat(),
        "top_movers": movers[:10],
        "opportunities": opportunities,
        "watched": watched[:6],
    }
