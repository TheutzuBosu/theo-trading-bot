# Progres Theo Trading Bot

Statusuri: De făcut · În lucru · Gata · Blocat

| # | Etapă | Status | Branch | Agent | Note |
|---|---|---|---|---|---|
| 0 | Fundația | Gata | main | Antigravity | uv, Python 3.12, pyproject.toml, ruff, pytest, CI verde |
| 1 | Date | Gata | etapa-1-date | Antigravity | Univers S&P 100, cache parquet/csv, drop_incomplete_bar, validate, loader daily & recent |
| 2 | Backtester | Gata | etapa-2-backtester | Claude Code | Indicatori, motor bar-cu-bar, metrici, walk-forward, Monte Carlo, test aleator, detector look-ahead |
| 3 | Strategii + Poarta 1 | În lucru | etapa-3-strategii | Claude Code | Decide dacă proiectul continuă; S1–S4 |
| 4 | Risk guard | De făcut | etapa-4-risc | Claude Code | |
| 5 | Broker Alpaca paper | De făcut | etapa-5-broker | Claude Code | |
| 6 | Stare, veto, post-mortem | De făcut | etapa-6-stare-ai | Antigravity | |
| 7 | Rulare zilnică + Telegram | De făcut | etapa-7-rulare | Antigravity + review Claude Code | |
| 8 | Dashboard | De făcut | etapa-8-dashboard | Antigravity | Poate începe pe date de exemplu |
| 9 | Review, Poarta 2, fiscal | De făcut | etapa-9-raportare | Antigravity | |
| 10 | Bani reali | Blocat | etapa-10-live | Claude Code | Doar după Poarta 2 și `LIVE_APPROVED.md` |

## Pasul următor exact

Etapa 3 (Claude Code), pe branch-ul `etapa-3-strategii`:
- 3a gata: MACD în `src/indicators.py`; `src/strategies/` cu S1–S4 (`load_strategy("S1")` → `StrategySpec` cu
  `signals`, `params`, `max_hold_bars`); parametrii în `config/strategies.yaml`; 106 teste verzi.
- 3b (următorul): descarci o dată datele 2006–azi pentru universul din `config/universe.csv` + SPY (`load_daily`,
  cache în `data/cache/`); pentru fiecare strategie: `walk_forward`, `monte_carlo`, `random_entry_test` (500) și
  testul ±20% (`load_strategy(name, overrides=...)`); `reports/gate1.md` cu PASS/FAIL pe cele 7 criterii, SPY,
  nota despre survivorship bias, grafice equity vs SPY în `reports/`. NU optimizezi parametrii. Rezultatele lungi
  în `.cache/`. Întâi: decizia proprietarului despre acțiuni întregi vs fracționare (vezi „Pentru proprietar”).

## Pentru proprietar

- Cheile sunt în `.env` (3 noiembrie 2026): Alpaca, Finnhub, Gemini, Telegram, parola dashboard. GH_DISPATCH_TOKEN e și el pus.
- Contul Alpaca: paper „TRADING”, 500 $. `BOT_CAPITAL=500`.
- De decis înainte de Poarta 1: acțiuni întregi vs fracționare la 500 $ (vezi `docs/HANDOFF.md`, Blocaje).

## Bug-uri cunoscute

Niciunul. 106 teste pytest trecute offline.

## Ultima actualizare

3 noiembrie 2026 · Claude Code · Etapa 3a (strategiile S1–S4) finalizată.
