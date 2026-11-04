"""News risk veto using Finnhub headlines + Gemini Flash-Lite (Faza B, B4).

Rule 6 (`AGENTS.md`): AI can only say NO (veto on extreme crisis / shock / halt headlines)
and explain in simple Romanian. It never generates buy/sell signals or overrides the risk guard.
If Finnhub or Gemini is unavailable, fails open (`allow=True`) so the mechanical rules decide.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

import requests

from src.config import settings

FINNHUB_COMPANY_NEWS_URL = "https://finnhub.io/api/v1/company-news"
CRISIS_KEYWORDS = (
    "trading halt",
    "circuit breaker",
    "emergency rate",
    "flash crash",
    "exchange halted",
)


def fetch_recent_news(
    symbol: str,
    finnhub_key: str | None = None,
    session: Any = None,
    lookback_hours: int = 4,
    now_utc: datetime | None = None,
) -> list[dict[str, Any]]:
    """Fetch recent news for `symbol` from Finnhub; returns `[]` on error or missing key."""
    key = finnhub_key if finnhub_key is not None else settings.FINNHUB_API_KEY
    if not key:
        return []

    now = now_utc or datetime.now(timezone.utc)
    start_dt = now - timedelta(hours=lookback_hours)
    params = {
        "symbol": symbol.upper(),
        "from": start_dt.strftime("%Y-%m-%d"),
        "to": now.strftime("%Y-%m-%d"),
        "token": key,
    }
    http = session or requests
    try:
        resp = http.get(FINNHUB_COMPANY_NEWS_URL, params=params, timeout=3.0)
        if getattr(resp, "status_code", 500) != 200:
            return []
        items = resp.json()
        if not isinstance(items, list):
            return []
        cutoff_ts = start_dt.timestamp()
        recent = [
            it
            for it in items
            if isinstance(it, dict) and float(it.get("datetime", cutoff_ts)) >= cutoff_ts
        ]
        return recent[:10]
    except Exception:
        return []


def check_news_veto(
    symbol: str,
    direction: str,
    headlines: list[str],
    client: Any = None,
) -> tuple[bool, str]:
    """Return `(allow, reason_ro)` for a proposed entry given recent headlines."""
    clean = [h.strip() for h in headlines if h and h.strip()]
    if not clean:
        return True, "Fără știri majore recente."

    # Deterministic check for explicit exchange halt / circuit breaker keywords
    joined_lower = " | ".join(clean).lower()
    for kw in CRISIS_KEYWORDS:
        if kw in joined_lower:
            return False, f"Veto știri: s-a detectat alertă critică de piață ('{kw}')."

    if client is None:
        return True, "Știri verificate mecanic; nicio alertă de oprire a pieței."

    prompt = (
        f"Ești un filtru de risc. Avem un semnal {direction} pe {symbol}. "
        'Răspunde DOAR în JSON valid `{"allow": true/false, "reason": "1 frază în română"}`. '
        "Blochează (`allow: false`) DOAR dacă există o știre de criză extremă, oprire de "
        "tranzacționare sau șoc macroeconomic neașteptat în ultimele ore. Nu genera semnale noi.\n"
        "Titluri recente:\n- " + "\n- ".join(clean[:8])
    )
    try:
        model_name = settings.GEMINI_MODEL
        if model_name == "gemini-2.5-flash-lite":
            model_name = "gemini-flash-lite-latest"
        resp = client.models.generate_content(model=model_name, contents=prompt)
        raw = (getattr(resp, "text", None) or "").strip()
        if raw.startswith("```"):
            raw = raw.strip("`").removeprefix("json").strip()
        parsed = json.loads(raw)
        allow = bool(parsed.get("allow", True))
        reason = str(parsed.get("reason", "")).strip() or "Verificat de filtrul AI."
        return allow, reason
    except Exception:
        return True, "Fallback mecanic: filtrul AI indisponibil, intrare permisă de reguli."


__all__ = [
    "CRISIS_KEYWORDS",
    "FINNHUB_COMPANY_NEWS_URL",
    "check_news_veto",
    "fetch_recent_news",
]
