"""Weekend deep research & weekly strategic prep with Gemini AI (Faza B & Weekend Module).

Runs every Sunday evening (e.g. 20:00 RO / 18:00 UTC / 13:00 ET):
1. Analyzes the past week's trading performance & autopsy lessons from `state/trades.csv` and `autopsies.jsonl`.
2. Scans weekend financial headlines and upcoming mega-cap earnings calendar for the coming week.
3. Uses Gemini AI to synthesize:
   - Weekly trade retrospective & tactical lessons learned.
   - Macroeconomic outlook (FED, CPI/inflation, geopolitical, market regime).
   - Key high-impact events calendar for the upcoming week.
   - Strategic tactical game plan & watchlist for Monday market open.
4. Updates `state/summary.json` (`weekend_briefing`) for the Vercel dashboard and sends a Telegram alert.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd
import requests

from src.ai.premarket import MEGA_CAP_WATCHLIST, fetch_general_market_news
from src.config import settings
from src.state.store import StateStore

logger = logging.getLogger(__name__)

FINNHUB_EARNINGS_URL = "https://finnhub.io/api/v1/calendar/earnings"


def fetch_upcoming_earnings(
    start_date: str,
    end_date: str,
    finnhub_key: str | None = None,
    session: Any = None,
    limit: int = 12,
) -> list[dict[str, Any]]:
    """Fetch earnings releases for the upcoming week, prioritizing major companies."""
    key = (finnhub_key if finnhub_key is not None else settings.FINNHUB_API_KEY).strip()
    if not key:
        return []
    http = session or requests
    try:
        resp = http.get(
            FINNHUB_EARNINGS_URL,
            params={"from": start_date, "to": end_date, "token": key},
            timeout=10,
        )
        if resp.status_code != 200:
            return []
        items = resp.json().get("earningsCalendar", [])
        if not items:
            return []

        major: list[dict[str, Any]] = []
        others: list[dict[str, Any]] = []
        for it in items:
            sym = str(it.get("symbol", "")).upper()
            if not sym:
                continue
            record = {
                "date": str(it.get("date", "")),
                "symbol": sym,
                "hour": str(it.get("hour", "")).lower(),
                "eps_estimate": it.get("epsEstimate"),
                "revenue_estimate": it.get("revenueEstimate"),
            }
            if sym in MEGA_CAP_WATCHLIST:
                major.append(record)
            else:
                others.append(record)

        major.sort(key=lambda x: str(x.get("date", "")))
        others.sort(key=lambda x: str(x.get("date", "")))
        return (major + others)[:limit]
    except Exception as exc:  # noqa: BLE001
        logger.warning("Eroare la citirea calendarului de raportări săptămânal: %s", exc)
        return []


def summarize_weekly_performance(state_dir: Path) -> dict[str, Any]:
    """Calculate weekly metrics and collect lessons from closed trades and autopsies."""
    store = StateStore(state_dir)
    trades_df = store.read_trades()
    autopsies = store.read_autopsies()

    total_trades = len(trades_df)
    if total_trades == 0:
        return {
            "total_trades": 0,
            "win_rate_pct": 0.0,
            "total_pnl": 0.0,
            "winning_trades": 0,
            "losing_trades": 0,
            "best_trade": "N/A",
            "worst_trade": "N/A",
            "lessons": [],
        }

    pnl_series = pd.to_numeric(trades_df["pnl"], errors="coerce").fillna(0.0)
    wins = int((pnl_series > 0).sum())
    losses = int((pnl_series <= 0).sum())
    win_rate = round((wins / total_trades) * 100.0, 1) if total_trades > 0 else 0.0
    total_pnl = round(float(pnl_series.sum()), 2)

    best_idx = pnl_series.idxmax()
    worst_idx = pnl_series.idxmin()

    best_trade = (
        f"{trades_df.loc[best_idx, 'symbol']} ({trades_df.loc[best_idx, 'direction'].upper()}) "
        f"{float(pnl_series.loc[best_idx]):+.2f} $"
        if best_idx in trades_df.index
        else "N/A"
    )
    worst_trade = (
        f"{trades_df.loc[worst_idx, 'symbol']} ({trades_df.loc[worst_idx, 'direction'].upper()}) "
        f"{float(pnl_series.loc[worst_idx]):+.2f} $"
        if worst_idx in trades_df.index
        else "N/A"
    )

    # Collect lessons from trade entry/exit reasons and autopsies
    lessons: list[str] = []
    if "entry_reason" in trades_df.columns:
        for r in trades_df["entry_reason"].dropna().tolist():
            if "Lecție:" in str(r):
                lesson_part = str(r).split("Lecție:", 1)[1].strip().rstrip(". ")
                if lesson_part and lesson_part not in lessons:
                    lessons.append(lesson_part)

    for a in autopsies:
        les = str(a.get("lesson") or a.get("lesson_ro") or "").strip()
        if les and les not in lessons:
            lessons.append(les)

    return {
        "total_trades": total_trades,
        "win_rate_pct": win_rate,
        "total_pnl": total_pnl,
        "winning_trades": wins,
        "losing_trades": losses,
        "best_trade": best_trade,
        "worst_trade": worst_trade,
        "lessons": lessons[:5],
    }


def build_weekend_briefing(
    *,
    state_dir: Path,
    finnhub_key: str | None = None,
    gemini_client: Any = None,
    session: Any = None,
    now_utc: datetime | None = None,
) -> dict[str, Any]:
    """Generate a comprehensive weekend research and strategic briefing with Gemini AI."""
    now = now_utc or datetime.now(UTC)
    next_week_start = (now + timedelta(days=1)).strftime("%Y-%m-%d")
    next_week_end = (now + timedelta(days=7)).strftime("%Y-%m-%d")

    perf = summarize_weekly_performance(state_dir)
    news = fetch_general_market_news(finnhub_key=finnhub_key, session=session, limit=10)
    earnings = fetch_upcoming_earnings(
        next_week_start, next_week_end, finnhub_key=finnhub_key, session=session, limit=8
    )

    headlines = [str(n.get("headline", "")) for n in news if n.get("headline")][:8]
    earn_symbols = [f"{e['symbol']} ({e['date']})" for e in earnings]

    # Default fallback briefing in Romanian
    period_str = f"{now.strftime('%d %b')} – {(now + timedelta(days=5)).strftime('%d %b %Y')}"
    fallback: dict[str, Any] = {
        "updated_at": now.isoformat(),
        "period": period_str,
        "executive_summary_ro": (
            f"Analiză strategică de weekend pentru {period_str}. În ultima sesiune botul a înregistrat "
            f"{perf['total_trades']} tranzacții închise cu un PnL de {perf['total_pnl']:+.2f} $. "
            "Piața rămâne activă, iar atenția se concentrează pe raportările financiare majore ale săptămânii."
        ),
        "weekly_performance": {
            "total_trades": perf["total_trades"],
            "win_rate_pct": perf["win_rate_pct"],
            "total_pnl": perf["total_pnl"],
            "best_trade": perf["best_trade"],
            "worst_trade": perf["worst_trade"],
        },
        "lessons_learned": perf["lessons"] or [
            "Stop-loss-urile automate au protejat capitalul de pierderi mari în fazele de zgomot intraday.",
            "Evitarea cumpărărilor de impuls pe vârfuri fără volum susținut la deschidere.",
        ],
        "macro_outlook_ro": (
            "Contextul macroeconomic reflectă stabilitate cu tendință de impuls pe indicii principali "
            "(SPY / QQQ). Atenție la reacțiile de după raportările financiare din sectorul tech și sănătate."
        ),
        "key_events": [
            {
                "day": "Luni",
                "event": "Deschiderea săptămânii & scanarea gap-urilor de weekend",
                "impact": "MEDIUM",
            },
            {
                "day": "Miercuri",
                "event": "Date macroeconomice & raportări majore în desfășurare",
                "impact": "HIGH",
            },
            {
                "day": "Vineri",
                "event": "Închiderea pozițiilor săptămânale & reechilibrare",
                "impact": "MEDIUM",
            },
        ],
        "tactical_plan_ro": (
            "Plan tactic: Menținerea mizelor moderate (20 $ - 35 $ per acțiune, risc 0.5% pe SPY/QQQ). "
            "Prioritate acordată configurațiilor de rebound tehnic (oversold bounce) cu raport R:R minim 1:3. "
            "Filtrare strictă a tranzacțiilor la deschiderea de luni pentru a evita capcanele de pre-market."
        ),
        "watchlist": [
            {
                "symbol": "SPY",
                "direction": "long",
                "thesis_ro": "Continuarea trendului ascendent pe fondul optimismului economic general.",
            },
            {
                "symbol": "QQQ",
                "direction": "long",
                "thesis_ro": "Sectorul tehnologic susține raliul, oportunități pe spargeri de nivel.",
            },
            {
                "symbol": "LYEL",
                "direction": "long",
                "thesis_ro": "Impuls solid din date clinice și plasament privat, monitorizare trailing stop.",
            },
        ],
    }

    if gemini_client is None:
        return fallback

    prompt = (
        "Ești Chief Quantitative Strategist și AI Trading Mentor pentru Theo Trading Bot (bot intraday pe acțiuni US și SPY/QQQ).\n"
        "Este weekend și pregătim BRIEFING-UL STRATEGIC AL SĂPTĂMÂNII pentru săptămâna care urmează.\n\n"
        f"PERFORMANȚA RECENTĂ A BOTULUI:\n"
        f"- Tranzacții totale închise: {perf['total_trades']}\n"
        f"- Rată de câștig (Win Rate): {perf['win_rate_pct']}%\n"
        f"- PnL total realizat: {perf['total_pnl']:+.2f} $\n"
        f"- Cel mai bun trade: {perf['best_trade']}\n"
        f"- Cel mai slab trade: {perf['worst_trade']}\n"
        f"- Lecții extrase din autopsiile recente: {json.dumps(perf['lessons'], ensure_ascii=False)}\n\n"
        f"ȘTIRI FINANCIARE RECENTE DIN WEEKEND:\n- "
        + "\n- ".join(headlines)
        + "\n\n"
        f"RAPORTĂRI FINANCIARE (EARNINGS) URMĂTOAREA SĂPTĂMÂNĂ:\n"
        f"- {', '.join(earn_symbols) if earn_symbols else 'Nicio companie mega-cap cu raportare critică'}\n\n"
        "Generează un răspuns STRICT în JSON valid (fără markdown exterior) cu următoarea structură exactă:\n"
        "{\n"
        '  "period": "ex: 4 - 8 Noiembrie 2026",\n'
        '  "executive_summary_ro": "3 fraze în română clară și analitică: sinteza săptămânii trecute și viziunea pentru săptămâna viitoare",\n'
        '  "lessons_learned": [\n'
        '    "Lecția 1 concretă despre greșeli, stop-loss sau psihologia pieței",\n'
        '    "Lecția 2...",\n'
        '    "Lecția 3..."\n'
        "  ],\n"
        '  "macro_outlook_ro": "2-3 fraze despre contextul macro: inflație, FED, dobânzi, sentimentul general pe SPY și QQQ",\n'
        '  "key_events": [\n'
        '    {"day": "Luni", "event": "Descriere eveniment / raportare cheie", "impact": "HIGH" sau "MEDIUM" sau "LOW"},\n'
        '    {"day": "Miercuri", "event": "...", "impact": "HIGH"}\n'
        "  ],\n"
        '  "tactical_plan_ro": "Planul de acțiune pentru bot: reguli de risc, ore recomandate, ce greșeli din săptămâna trecută NU mai repetăm",\n'
        '  "watchlist": [\n'
        '    {"symbol": "SPY", "direction": "long", "thesis_ro": "De ce urmărim această acțiune/ETF"},\n'
        '    {"symbol": "...", "direction": "long sau short", "thesis_ro": "..."}\n'
        "  ]\n"
        "}"
    )

    models_to_try = [
        "gemini-flash-lite-latest",
        "gemini-2.5-flash",
        "gemini-2.0-flash",
    ]
    for model_name in models_to_try:
        try:
            resp = gemini_client.models.generate_content(model=model_name, contents=prompt)
            raw = (getattr(resp, "text", None) or "").strip()
            if raw.startswith("```"):
                raw = raw.strip("`").removeprefix("json").strip()
            parsed = json.loads(raw)

            fallback.update(
                {
                    "period": str(parsed.get("period") or fallback["period"]),
                    "executive_summary_ro": str(
                        parsed.get("executive_summary_ro") or fallback["executive_summary_ro"]
                    ),
                    "lessons_learned": list(
                        parsed.get("lessons_learned") or fallback["lessons_learned"]
                    ),
                    "macro_outlook_ro": str(
                        parsed.get("macro_outlook_ro") or fallback["macro_outlook_ro"]
                    ),
                    "key_events": list(parsed.get("key_events") or fallback["key_events"]),
                    "tactical_plan_ro": str(
                        parsed.get("tactical_plan_ro") or fallback["tactical_plan_ro"]
                    ),
                    "watchlist": list(parsed.get("watchlist") or fallback["watchlist"]),
                }
            )
            break
        except Exception as exc:  # noqa: BLE001
            logger.warning("Eroare la modelul %s în weekend_research: %s", model_name, exc)

    return fallback


def format_weekend_telegram_message(briefing: dict[str, Any]) -> str:
    """Format the weekend strategic research into an engaging Telegram report."""
    period = briefing.get("period", "Săptămâna Viitoare")
    exec_sum = briefing.get("executive_summary_ro", "")
    perf = briefing.get("weekly_performance", {})
    macro = briefing.get("macro_outlook_ro", "")
    plan = briefing.get("tactical_plan_ro", "")
    lessons = briefing.get("lessons_learned", [])
    events = briefing.get("key_events", [])
    watchlist = briefing.get("watchlist", [])

    lines = [
        f"🔬 *Theo Trading Bot — Raport Strategic de Weekend*",
        f"📅 *Perioada:* {period}\n",
        f"📋 *Sinteză Executivă:*",
        f"{exec_sum}\n",
        f"📊 *Performanță Cumulată:*",
        f"• Tranzacții: {perf.get('total_trades', 0)} (Win Rate: {perf.get('win_rate_pct', 0)}%)",
        f"• PnL realizat: {perf.get('total_pnl', 0.0):+.2f} $",
        f"• Cel mai bun trade: {perf.get('best_trade', 'N/A')}",
        f"• Cel mai slab trade: {perf.get('worst_trade', 'N/A')}\n",
    ]

    if lessons:
        lines.append("🧠 *Lecții Învățate din Erori:*")
        for les in lessons[:3]:
            lines.append(f"• {les}")
        lines.append("")

    if macro:
        lines.append(f"🌍 *Perspectivă Macro & Sentiment:*")
        lines.append(f"{macro}\n")

    if events:
        lines.append("🗓 *Evenimente Cheie ale Săptămânii:*")
        for ev in events[:4]:
            lines.append(f"• *{ev.get('day')}:* {ev.get('event')} [{ev.get('impact')}]")
        lines.append("")

    if plan:
        lines.append(f"🎯 *Plan Tactic pentru Luni:*")
        lines.append(f"{plan}\n")

    if watchlist:
        lines.append("👀 *Watchlist Săptămâna Viitoare:*")
        for w in watchlist[:4]:
            lines.append(
                f"• *{w.get('symbol')}* ({str(w.get('direction', '')).upper()}): {w.get('thesis_ro')}"
            )

    return "\n".join(lines)


def run_weekend_session(
    *,
    state_dir: Path,
    finnhub_key: str | None = None,
    gemini_client: Any = None,
    sync_github: bool = True,
    notify_telegram: bool = True,
) -> dict[str, Any]:
    """Execute complete weekend research routine, update summary.json, and sync state."""
    from src.alerts.telegram import send_telegram_message
    from src.live.state_writer import sync_state_dir_to_github

    store = StateStore(state_dir)
    briefing = build_weekend_briefing(
        state_dir=state_dir,
        finnhub_key=finnhub_key,
        gemini_client=gemini_client,
    )

    summary = store.read_summary()
    summary["weekend_briefing"] = briefing
    store.write_summary(summary)

    if sync_github:
        sync_state_dir_to_github(state_dir, token=settings.GH_DISPATCH_TOKEN)

    if notify_telegram:
        msg = format_weekend_telegram_message(briefing)
        send_telegram_message(msg)

    return briefing
