"""Telegram alerts in Romanian for Theo Trading Bot (Faza B, B6b).

Pure formatting functions + HTTP helpers (`send_telegram_message`, `fetch_chat_id`) that accept an
injected `requests.Session` (or similar object with `.get`/`.post`) for offline unit testing.
Never logs or raises raw URLs containing the bot token.
"""

from __future__ import annotations

import logging
from typing import Any

import requests

from src.config import settings

logger = logging.getLogger(__name__)

TELEGRAM_API_BASE = "https://api.telegram.org"
DEFAULT_TIMEOUT = 10

EXIT_REASON_RO = {
    "stop": "Oprit la pragul de protecție (stop-loss)",
    "target": "Țintă de profit atinsă",
    "eod": "Închis automat la finalul sesiunii (fără poziții peste noapte)",
}


def _fmt_usd(value: float, signed: bool = False) -> str:
    sign = "+" if (signed and value > 0) else ("−" if value < 0 else "")
    return f"{sign}{abs(value):.2f} $".replace(".", ",")


def _fmt_pct(value: float, signed: bool = False) -> str:
    sign = "+" if (signed and value > 0) else ("−" if value < 0 else "")
    return f"{sign}{abs(value):.2f}%".replace(".", ",")


def _fmt_r(value: float) -> str:
    sign = "+" if value > 0 else ("−" if value < 0 else "")
    return f"{sign}{abs(value):.2f} R".replace(".", ",")


def _direction_ro(direction: str) -> str:
    d = direction.strip().lower()
    if d == "long":
        return "LONG (cumpărare)"
    if d == "short":
        return "SHORT (vânzare în lipsă)"
    return direction.upper()


def format_entry_message(
    *,
    symbol: str,
    direction: str,
    qty: float,
    entry_price: float,
    stop: float,
    risk_pct: float,
    reason: str,
    strategy: str | None = None,
    mode: str = "PAPER",
) -> str:
    """Format an entry alert in simple Romanian.

    `risk_pct` can be passed either as a fraction (e.g. 0.005 for 0.5%) or already in percent (0.5)
    if > 0.05; values <= 0.05 are treated as fractions of equity (multiplied by 100).
    """
    risk_display = risk_pct * 100.0 if abs(risk_pct) <= 0.05 else risk_pct
    strat_part = f" · Strategie: {strategy}" if strategy else ""
    qty_str = f"{qty:.2f}".rstrip("0").rstrip(".").replace(".", ",")
    return (
        f"🟢 INTRARE [{mode}] — {symbol.upper()}\n"
        f"• Direcție: {_direction_ro(direction)}{strat_part}\n"
        f"• Cantitate: {qty_str} acțiuni la {_fmt_usd(entry_price)}\n"
        f"• Stop-loss: {_fmt_usd(stop)} (risc {_fmt_pct(risk_display)} din capital)\n"
        f"• De ce: {reason}"
    )


def format_exit_message(
    *,
    symbol: str,
    direction: str,
    pnl: float,
    r_multiple: float,
    exit_reason: str,
    exit_price: float | None = None,
    lesson: str | None = None,
    mode: str = "PAPER",
) -> str:
    """Format an exit alert in simple Romanian."""
    icon = "✅" if pnl >= 0 else "🔴"
    reason_ro = EXIT_REASON_RO.get(exit_reason.strip().lower(), exit_reason)
    price_part = f" la {_fmt_usd(exit_price)}" if exit_price is not None else ""
    lines = [
        f"{icon} IEȘIRE [{mode}] — {symbol.upper()} ({direction.strip().upper()}){price_part}",
        f"• Rezultat: {_fmt_usd(pnl, signed=True)} ({_fmt_r(r_multiple)})",
        f"• Motiv ieșire: {reason_ro}",
    ]
    if lesson:
        lines.append(f"• Observație: {lesson}")
    return "\n".join(lines)


def format_daily_summary_message(
    *,
    date: str,
    equity: float,
    daily_pnl: float,
    daily_pnl_pct: float,
    total_pnl: float,
    total_pnl_pct: float,
    trades_count: int,
    wins_count: int = 0,
    drawdown_pct: float = 0.0,
    mode: str = "PAPER",
) -> str:
    """Format the end-of-day summary in simple Romanian."""
    losses_count = max(trades_count - wins_count, 0)
    dp = f"{_fmt_usd(daily_pnl, signed=True)} ({_fmt_pct(daily_pnl_pct, signed=True)})"
    tp = f"{_fmt_usd(total_pnl, signed=True)} ({_fmt_pct(total_pnl_pct, signed=True)})"
    return (
        f"📊 REZUMAT ZILNIC [{mode}] — {date}\n"
        f"• Capital curent: {_fmt_usd(equity)}\n"
        f"• Profit azi: {dp}\n"
        f"• Profit total: {tp}\n"
        f"• Tranzacții azi: {trades_count} ({wins_count} câștigate, {losses_count} pierdute)\n"
        f"• Scădere față de vârf (drawdown): {_fmt_pct(drawdown_pct)}"
    )


def format_daily_loss_limit_message(
    *,
    daily_pnl: float,
    daily_pnl_pct: float,
    equity: float,
    limit_pct: float = -2.0,
    mode: str = "PAPER",
) -> str:
    """Format the daily loss limit (-2%) alert in Romanian."""
    loss_str = f"{_fmt_usd(daily_pnl, signed=True)} ({_fmt_pct(daily_pnl_pct, signed=True)})"
    return (
        f"⚠️ LIMITĂ ZILNICĂ ATINSĂ [{mode}] ({_fmt_pct(limit_pct)})\n"
        f"• Pierdere azi: {loss_str}\n"
        f"• Capital rămas: {_fmt_usd(equity)}\n"
        f"• Acțiune: Botul a oprit orice tranzacție nouă pentru restul zilei."
    )


def format_kill_message(
    *,
    reason: str,
    equity: float | None = None,
    closed_positions: int = 0,
    mode: str = "PAPER",
) -> str:
    """Format the emergency KILL switch alert in Romanian."""
    eq_line = f"• Capital curent: {_fmt_usd(equity)}\n" if equity is not None else ""
    return (
        f"🛑 OPRIRE DE URGENȚĂ (KILL) [{mode}]\n"
        f"• Motiv: {reason}\n"
        f"• Poziții închise la piață: {closed_positions}\n"
        f"{eq_line}"
        f"• Botul este blocat și nu va mai plasa ordine până la deblocarea manuală."
    )


def format_error_message(
    *,
    component: str,
    error: str,
    mode: str = "PAPER",
) -> str:
    """Format a runtime/workflow error alert in Romanian."""
    return f"🚨 EROARE BOT [{mode}]\n• Componentă: {component}\n• Detalii: {error}"


def fetch_chat_id(
    token: str | None = None,
    session: Any | None = None,
    timeout: int = DEFAULT_TIMEOUT,
) -> str | None:
    """Fetch the most recent Telegram `chat.id` from `getUpdates`.

    Returns the chat ID as a string, or None if no updates exist or the call fails.
    """
    bot_token = (token if token is not None else settings.TELEGRAM_BOT_TOKEN).strip()
    if not bot_token:
        logger.warning("TELEGRAM_BOT_TOKEN is missing; cannot call getUpdates.")
        return None

    http = session or requests
    url = f"{TELEGRAM_API_BASE}/bot{bot_token}/getUpdates"
    try:
        resp = http.get(url, timeout=timeout)
        if resp.status_code != 200:
            logger.warning("Telegram getUpdates failed with HTTP %s", resp.status_code)
            return None
        payload = resp.json()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Telegram getUpdates request error: %s", type(exc).__name__)
        return None

    if not payload.get("ok"):
        return None

    results = payload.get("result") or []
    for item in reversed(results):
        for key in ("message", "edited_message", "channel_post", "my_chat_member"):
            msg = item.get(key)
            if isinstance(msg, dict):
                chat = msg.get("chat")
                if isinstance(chat, dict) and chat.get("id") is not None:
                    return str(chat["id"])
    return None


def send_telegram_message(
    text: str,
    *,
    token: str | None = None,
    chat_id: str | None = None,
    session: Any | None = None,
    timeout: int = DEFAULT_TIMEOUT,
) -> bool:
    """Send a plain-text message to Telegram.

    If `chat_id` is empty, automatically tries `fetch_chat_id` once.
    Returns True if delivered (`ok: true`), False otherwise.
    """
    bot_token = (token if token is not None else settings.TELEGRAM_BOT_TOKEN).strip()
    if not bot_token:
        logger.warning("TELEGRAM_BOT_TOKEN is missing; cannot send Telegram alert.")
        return False

    target_chat = (chat_id if chat_id is not None else settings.TELEGRAM_CHAT_ID).strip()
    if not target_chat:
        target_chat = fetch_chat_id(token=bot_token, session=session, timeout=timeout) or ""
    if not target_chat:
        logger.warning("TELEGRAM_CHAT_ID is missing and getUpdates returned no chat.")
        return False

    http = session or requests
    url = f"{TELEGRAM_API_BASE}/bot{bot_token}/sendMessage"
    try:
        resp = http.post(
            url,
            json={
                "chat_id": target_chat,
                "text": text,
                "disable_web_page_preview": True,
            },
            timeout=timeout,
        )
        if resp.status_code != 200:
            logger.warning("Telegram sendMessage failed with HTTP %s", resp.status_code)
            return False
        data = resp.json()
        return bool(data.get("ok"))
    except Exception as exc:  # noqa: BLE001
        logger.warning("Telegram sendMessage request error: %s", type(exc).__name__)
        return False


def send_entry_alert(
    *,
    token: str | None = None,
    chat_id: str | None = None,
    session: Any | None = None,
    **kwargs: Any,
) -> bool:
    return send_telegram_message(
        format_entry_message(**kwargs), token=token, chat_id=chat_id, session=session
    )


def send_exit_alert(
    *,
    token: str | None = None,
    chat_id: str | None = None,
    session: Any | None = None,
    **kwargs: Any,
) -> bool:
    return send_telegram_message(
        format_exit_message(**kwargs), token=token, chat_id=chat_id, session=session
    )


def send_daily_summary_alert(
    *,
    token: str | None = None,
    chat_id: str | None = None,
    session: Any | None = None,
    **kwargs: Any,
) -> bool:
    return send_telegram_message(
        format_daily_summary_message(**kwargs), token=token, chat_id=chat_id, session=session
    )


def send_daily_loss_limit_alert(
    *,
    token: str | None = None,
    chat_id: str | None = None,
    session: Any | None = None,
    **kwargs: Any,
) -> bool:
    return send_telegram_message(
        format_daily_loss_limit_message(**kwargs), token=token, chat_id=chat_id, session=session
    )


def send_kill_alert(
    *,
    token: str | None = None,
    chat_id: str | None = None,
    session: Any | None = None,
    **kwargs: Any,
) -> bool:
    return send_telegram_message(
        format_kill_message(**kwargs), token=token, chat_id=chat_id, session=session
    )


def send_error_alert(
    *,
    token: str | None = None,
    chat_id: str | None = None,
    session: Any | None = None,
    **kwargs: Any,
) -> bool:
    return send_telegram_message(
        format_error_message(**kwargs), token=token, chat_id=chat_id, session=session
    )
