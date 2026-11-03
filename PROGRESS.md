# Progres Theo Trading Bot

Statusuri: De făcut · În lucru · Gata · Blocat

| # | Etapă | Status | Branch | Agent | Note |
|---|---|---|---|---|---|
| 0 | Fundația | În lucru | main | Claude (chat) → Antigravity | Fișierele de reguli gata (3 noiembrie 2026). Rămân 0a și 0b din `docs/PLAN.md` |
| 1 | Date | De făcut | etapa-1-date | Antigravity | |
| 2 | Backtester | De făcut | etapa-2-backtester | Claude Code | |
| 3 | Strategii + Poarta 1 | De făcut | etapa-3-strategii | Claude Code | Decide dacă proiectul continuă |
| 4 | Risk guard | De făcut | etapa-4-risc | Claude Code | |
| 5 | Broker Alpaca paper | De făcut | etapa-5-broker | Claude Code | |
| 6 | Stare, veto, post-mortem | De făcut | etapa-6-stare-ai | Antigravity | |
| 7 | Rulare zilnică + Telegram | De făcut | etapa-7-rulare | Antigravity + review Claude Code | |
| 8 | Dashboard | De făcut | etapa-8-dashboard | Antigravity | Poate începe pe date de exemplu |
| 9 | Review, Poarta 2, fiscal | De făcut | etapa-9-raportare | Antigravity | |
| 10 | Bani reali | Blocat | etapa-10-live | Claude Code | Doar după Poarta 2 și `LIVE_APPROVED.md` |

## Pasul următor exact

Etapa 0, sub-pasul 0a (Antigravity), pe `main`: creează `pyproject.toml` cu uv (Python 3.12) și dependențele din
`docs/PLAN.md`, `scripts/check_fast.sh`, `scripts/check.sh`, un test trivial în `tests/`, `.github/workflows/ci.yml`.
Gata când `scripts/check.sh` trece local. Apoi 0b: repo privat pe GitHub cu `gh`, push, CI verde.

## Pentru proprietar

- Rulează `bash scripts/set_keys.sh` din Terminal, în acest folder (pune cheile în `.env`). Minimum: cheile Alpaca.
- Contul Alpaca: paper „TRADING”, 500 $. `BOT_CAPITAL=500`.

## Bug-uri cunoscute

Niciunul.

## Ultima actualizare

3 noiembrie 2026 · Claude (chat) · Etapa 0: fișierele de reguli.
