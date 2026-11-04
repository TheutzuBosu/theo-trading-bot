"""Pre-market intelligence scanner: SPY/QQQ pre-market gap, macro news & earnings (Faza B).

Scans before and during the US session:
1. Pre-market price action and gap % on `SPY` and `QQQ` (vs previous regular close).
2. Market-wide macro/financial headlines (`finnhub.io/api/v1/news?category=general`) +
   ETF headlines (`company-news` for `SPY`/`QQQ`).
3. Today's earnings calendar (`finnhub.io/api/v1/calendar/earnings`) for major US companies.
4. Synthesizes a concise Romanian briefing with Gemini (`gemini-2.5-flash-lite`) or a
   deterministic fallback, saved into `state/summary.json` (`premarket`) for the dashboard
   and sent to Telegram.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any

import requests

from src.ai.veto import CRISIS_KEYWORDS, fetch_recent_news
from src.config import settings

logger = logging.getLogger(__name__)

FINNHUB_GENERAL_NEWS_URL = "https://finnhub.io/api/v1/news"
FINNHUB_EARNINGS_URL = "https://finnhub.io/api/v1/calendar/earnings"

MEGA_CAP_WATCHLIST = frozenset(
    {
        "AAPL",
        "MSFT",
        "NVDA",
        "AMZN",
        "GOOGL",
        "GOOG",
        "META",
        "TSLA",
        "AVGO",
        "BRK.B",
        "JPM",
        "LLY",
        "V",
        "UNH",
        "XOM",
        "MA",
        "COST",
        "HD",
        "PG",
        "NFLX",
        "AMD",
        "CRM",
        "BAC",
        "ORCL",
        "WMT",
    }
)


def fetch_general_market_news(
    finnhub_key: str | None = None,
    session: Any = None,
    limit: int = 8,
) -> list[dict[str, Any]]:
    """Fetch top general financial & macroeconomic news from Finnhub."""
    key = (finnhub_key if finnhub_key is not None else settings.FINNHUB_API_KEY).strip()
    if not key:
        return []
    http = session or requests
    try:
        resp = http.get(
            FINNHUB_GENERAL_NEWS_URL,
            params={"category": "general", "token": key},
            timeout=5.0,
        )
        if getattr(resp, "status_code", 500) != 200:
            return []
        items = resp.json()
        if not isinstance(items, list):
            return []
        out: list[dict[str, Any]] = []
        for it in items:
            if isinstance(it, dict) and it.get("headline"):
                out.append(
                    {
                        "headline": str(it["headline"]).strip(),
                        "source": str(it.get("source", "Finnhub")).strip(),
                        "summary": str(it.get("summary", "")).strip()[:240],
                        "datetime": it.get("datetime"),
                    }
                )
            if len(out) >= limit:
                break
        return out
    except Exception as exc:  # noqa: BLE001
        logger.warning("Eroare la citirea știrilor generale Finnhub: %s", type(exc).__name__)
        return []


def fetch_todays_earnings(
    date_str: str | None = None,
    finnhub_key: str | None = None,
    session: Any = None,
) -> list[dict[str, Any]]:
    """Fetch today's financial/earnings reports from Finnhub, prioritizing S&P 100 mega-caps."""
    key = (finnhub_key if finnhub_key is not None else settings.FINNHUB_API_KEY).strip()
    if not key:
        return []
    day = date_str or datetime.now(UTC).strftime("%Y-%m-%d")
    http = session or requests
    try:
        resp = http.get(
            FINNHUB_EARNINGS_URL,
            params={"from": day, "to": day, "token": key},
            timeout=5.0,
        )
        if getattr(resp, "status_code", 500) != 200:
            return []
        payload = resp.json()
        cal = payload.get("earningsCalendar") if isinstance(payload, dict) else []
        if not isinstance(cal, list):
            return []

        major: list[dict[str, Any]] = []
        others: list[dict[str, Any]] = []
        for item in cal:
            if not isinstance(item, dict):
                continue
            sym = str(item.get("symbol") or "").upper().strip()
            if not sym:
                continue
            rev_est = float(item.get("revenueEstimate") or 0.0)
            rec = {
                "symbol": sym,
                "hour": str(item.get("hour") or ""),  # bmo = before market open, amc = after close
                "eps_estimate": item.get("epsEstimate"),
                "eps_actual": item.get("epsActual"),
                "revenue_estimate": item.get("revenueEstimate"),
                "revenue_actual": item.get("revenueActual"),
            }
            if sym in MEGA_CAP_WATCHLIST:
                major.append(rec)
            elif rev_est >= 500_000_000 and len(others) < 6:
                others.append(rec)
        return (major + others)[:6]
    except Exception as exc:  # noqa: BLE001
        logger.warning("Eroare la citirea calendarului de raportări: %s", type(exc).__name__)
        return []


def build_premarket_briefing(
    *,
    quotes: dict[str, dict[str, float]],
    finnhub_key: str | None = None,
    gemini_client: Any = None,
    session: Any = None,
    now_utc: datetime | None = None,
    opportunities: list[dict[str, Any]] | None = None,
    top_movers: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build a complete Pre-Market & Financial News intelligence object in Romanian."""
    now = now_utc or datetime.now(UTC)
    general_news = fetch_general_market_news(finnhub_key=finnhub_key, session=session, limit=6)
    spy_news = fetch_recent_news(
        "SPY", finnhub_key=finnhub_key, session=session, lookback_hours=12, now_utc=now
    )
    qqq_news = fetch_recent_news(
        "QQQ", finnhub_key=finnhub_key, session=session, lookback_hours=12, now_utc=now
    )
    earnings = fetch_todays_earnings(
        date_str=now.strftime("%Y-%m-%d"), finnhub_key=finnhub_key, session=session
    )

    seen: set[str] = set()
    headlines: list[str] = []
    for item in general_news + spy_news[:4] + qqq_news[:4]:
        h = str(item.get("headline") or "").strip()
        if h and h not in seen:
            seen.add(h)
            headlines.append(h)
        if len(headlines) >= 8:
            break

    spy_q = quotes.get("SPY", {})
    qqq_q = quotes.get("QQQ", {})
    spy_gap = float(spy_q.get("gap_pct", 0.0))
    qqq_gap = float(qqq_q.get("gap_pct", 0.0))

    joined_lower = " | ".join(headlines).lower()
    crisis_hit = next((kw for kw in CRISIS_KEYWORDS if kw in joined_lower), None)
    if crisis_hit:
        risk_regime = "CRIZĂ (Veto activ)"
    elif (
        abs(spy_gap) >= 1.0
        or abs(qqq_gap) >= 1.2
        or any(e["symbol"] in MEGA_CAP_WATCHLIST for e in earnings)
    ):
        risk_regime = "ATENȚIE (Mișcare Pre-Market / Raportări financiare)"
    else:
        risk_regime = "NORMAL"

    def _hour_label(h: str) -> str:
        if h == "bmo":
            return "înainte de deschidere"
        if h == "amc":
            return "după închidere"
        return "azi"

    earnings_syms = [f"{e['symbol']} ({_hour_label(str(e.get('hour', '')))})" for e in earnings[:5]]

    # Deterministic fallback summary in Romanian
    spy_p = float(spy_q.get("price", 0.0))
    qqq_p = float(qqq_q.get("price", 0.0))
    dir_word = (
        "în creștere ușoară"
        if (spy_gap + qqq_gap) > 0.15
        else "în scădere ușoară"
        if (spy_gap + qqq_gap) < -0.15
        else "aproape de închiderea de ieri (consolidare)"
    )
    earn_text = (
        f" Raportări financiare urmărite azi: {', '.join(earnings_syms)}."
        if earnings_syms
        else " Fără raportări financiare mega-cap care să blocheze deschiderea."
    )
    default_explanation = (
        f"În Pre-Market, piața SUA este {dir_word}: SPY la {spy_p:.2f} $ ({spy_gap:+.2f}%) "
        f"și QQQ la {qqq_p:.2f} $ ({qqq_gap:+.2f}%).{earn_text} "
        f"La 16:30 (09:30 ET) botul măsoară banda de zgomot și VWAP-ul, iar de la 17:12 (10:12 ET) "
        f"execută automat pe direcția spargerii (Long sau Short cu levier 2x)."
    )

    explanation_ro = default_explanation
    if gemini_client is not None and headlines:
        earn_str = ", ".join(earnings_syms) if earnings_syms else "niciuna majoră"
        prompt = (
            "Ești analistul de pre-market al botului intraday Theo Trading Bot (SPY și QQQ). "
            f"Prețuri Pre-Market: SPY = {spy_p:.2f}$ (gap {spy_gap:+.2f}%), "
            f"QQQ = {qqq_p:.2f}$ (gap {qqq_gap:+.2f}%). "
            f"Raportări financiare azi: {earn_str}.\n"
            "Știri recente:\n- " + "\n- ".join(headlines[:6]) + "\n\nRăspunde DOAR în JSON valid "
            '`{"explanation_ro": "2-3 fraze clare în română simplă"}` '
            "care explică de ce este piața la acest nivel în pre-market, ce știri sau raportări "
            "financiare contează azi și ce direcție (Long/Short) e favorizată la deschidere."
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
            cand_text = str(parsed.get("explanation_ro") or "").strip()
            if cand_text:
                explanation_ro = cand_text
        except Exception as exc:  # noqa: BLE001
            logger.warning("Fallback mecanic la sinteza Gemini pre-market: %s", type(exc).__name__)

    return {
        "updated_at": now.isoformat(),
        "risk_regime": risk_regime,
        "quotes": {
            "SPY": {
                "price": round(spy_p, 2),
                "prev_close": round(float(spy_q.get("prev_close", spy_p)), 2),
                "gap_pct": round(spy_gap, 2),
            },
            "QQQ": {
                "price": round(qqq_p, 2),
                "prev_close": round(float(qqq_q.get("prev_close", qqq_p)), 2),
                "gap_pct": round(qqq_gap, 2),
            },
        },
        "explanation_ro": explanation_ro,
        "headlines": headlines[:6],
        "earnings_today": earnings[:5],
        "opportunities": opportunities or [],
        "top_movers": top_movers or [],
    }


def format_premarket_telegram_message(briefing: dict[str, Any]) -> str:
    """Format the Pre-Market & Financial News briefing in Romanian for Telegram."""
    q = briefing.get("quotes") or {}
    spy = q.get("SPY") or {}
    qqq = q.get("QQQ") or {}
    spy_line = (
        f"• SPY (S&P 500): {float(spy.get('price', 0.0)):.2f} $ "
        f"({float(spy.get('gap_pct', 0.0)):+.2f}% față de închiderea de ieri)"
    ).replace(".", ",")
    qqq_line = (
        f"• QQQ (Nasdaq 100): {float(qqq.get('price', 0.0)):.2f} $ "
        f"({float(qqq.get('gap_pct', 0.0)):+.2f}% față de închiderea de ieri)"
    ).replace(".", ",")

    earnings = briefing.get("earnings_today") or []
    earn_syms = [str(e.get("symbol")) for e in earnings if e.get("symbol")]
    earn_line = (
        f"• Raportări financiare azi: {', '.join(earn_syms)}"
        if earn_syms
        else "• Raportări financiare azi: Nicio raportare mega-cap blocantă"
    )

    opps = (briefing.get("opportunities") or [])[:4]
    opp_block = ""
    if opps:
        opp_lines = []
        for op in opps:
            sym = op.get("symbol")
            d = str(op.get("direction", "long")).upper()
            gap = float(op.get("gap_pct", 0.0))
            stake = float(op.get("stake_dollars", 15.0))
            rr = float(op.get("rr_ratio", 3.5))
            opp_lines.append(
                f"  – {sym} ({gap:+.2f}%): {d} · miză {stake:.0f} $ · Risc:Reward 1:{rr:.1f}"
            )
        opp_block = "\n\n🎯 Oportunități detectate pe acțiuni individuale:\n" + "\n".join(opp_lines)

    headlines = (briefing.get("headlines") or [])[:3]
    news_block = ""
    if headlines:
        news_block = "\n\n📰 Știri principale:\n" + "\n".join(f"  – {h}" for h in headlines)

    return (
        f"🔎 ANALIZĂ PRE-MARKET, ACȚIUNI & ȘTIRI [PAPER]\n"
        f"{spy_line}\n"
        f"{qqq_line}\n"
        f"• Regim risc: {briefing.get('risk_regime', 'NORMAL')}\n"
        f"{earn_line}\n\n"
        f"💡 De ce se mișcă piața:\n{briefing.get('explanation_ro', '')}"
        f"{opp_block}"
        f"{news_block}"
    )
