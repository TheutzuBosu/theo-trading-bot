# Progres Theo Trading Bot

Statusuri: De făcut · În lucru · Gata · Blocat

| # | Etapă | Status | Branch | Agent | Note |
|---|---|---|---|---|---|
| 0 | Fundația | Gata | main | Antigravity | uv, Python 3.12, pyproject.toml, ruff, pytest, CI verde |
| 1 | Date | Gata | etapa-1-date | Antigravity | Univers S&P 100, cache parquet/csv, drop_incomplete_bar, validate, loader daily & recent |
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

Etapa 2 (Claude Code), pe branch-ul `etapa-2-backtester`:
- 2a: `src/indicators.py` (SMA, EMA, ATR(20), RSI(2), RSI(14), Donchian high/low, ADX(14), randament 12-1 luni) cu teste pe valori calculate de mână.
- 2b: `src/backtest/engine.py` bar-cu-bar conform regulilor comune din `docs/PLAN.md`.
- 2c: Metrici de performanță, walk-forward, Monte Carlo, intrări aleatoare.

## Pentru proprietar

- Cheile sunt în `.env` (3 noiembrie 2026): Alpaca, Finnhub, Gemini, Telegram, parola dashboard. GH_DISPATCH_TOKEN e și el pus.
- Contul Alpaca: paper „TRADING”, 500 $. `BOT_CAPITAL=500`.

## Bug-uri cunoscute

Niciunul. 28 de teste pytest trecute cu succes offline.

## Ultima actualizare

3 noiembrie 2026 · Antigravity · Etapa 1 (Date de piață) finalizată.
