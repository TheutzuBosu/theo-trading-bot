"""Faza B, B6b: wait for a message on @thetheotrading_bot (long-polling), save TELEGRAM_CHAT_ID
to .env, and send a single test message in Romanian. Places no trading orders.

Run: PYTHONPATH=. uv run python scripts/probe_telegram.py
"""

from __future__ import annotations

from pathlib import Path

import requests

from src.alerts.telegram import TELEGRAM_API_BASE, fetch_chat_id, send_telegram_message
from src.config import settings


def poll_for_chat_id(timeout_sec: int = 120) -> str | None:
    token = settings.TELEGRAM_BOT_TOKEN.strip()
    if not token:
        return None
    cid = settings.TELEGRAM_CHAT_ID.strip() or fetch_chat_id(token=token)
    if cid:
        return cid

    url = f"{TELEGRAM_API_BASE}/bot{token}/getUpdates"
    # Telegram server-side long polling (up to 4 x 30s = 120s)
    rounds = max(timeout_sec // 30, 1)
    for _ in range(rounds):
        try:
            resp = requests.get(url, params={"timeout": 30}, timeout=35)
            if resp.status_code == 200:
                cid = fetch_chat_id(token=token)
                if cid:
                    return cid
        except Exception:  # noqa: BLE001
            pass
    return None


def main() -> None:
    cid = poll_for_chat_id(120)
    if not cid:
        raise SystemExit("Nu am primit niciun mesaj pe Telegram în 2 minute.")

    env_path = Path(__file__).resolve().parent.parent / ".env"
    if env_path.exists():
        content = env_path.read_text(encoding="utf-8")
        if "TELEGRAM_CHAT_ID=" not in content:
            with env_path.open("a", encoding="utf-8") as f:
                f.write(f"\nTELEGRAM_CHAT_ID={cid}\n")

    ok = send_telegram_message(
        "🤖 Theo Trading Bot (Faza B · B6b): Alertele Telegram sunt conectate și funcționează! "
        "Acesta este mesajul de probă (nu s-a plasat niciun ordin).",
        chat_id=cid,
    )
    if not ok:
        raise SystemExit("Trimiterea mesajului de probă a eșuat.")
    print("TELEGRAM_PROBE_OK")


if __name__ == "__main__":
    main()
