# Progres Theo Trading Bot

Statusuri: De făcut · În lucru · Gata · Blocat · Oprit

**Proiectul e oprit (D19).** Nicio strategie nu bate SPY ajustat la risc după costuri (Poarta 1), nici după
iterația permisă (D18). Conform D7, nu se trece la paper trading și nici la bani reali.
Proprietarul a pornit apoi **Faza B: day trading SPY/QQQ, doar pe Alpaca Paper** (D20–D22, `docs/PLAN_DAYTRADING.md`).

| # | Faza B | Status | Branch | Agent | Note |
|---|---|---|---|---|---|
| B0 | Broker + cont demo | Gata | faza-b-daytrading | Claude Code | SIP 1 minut de la 2016 (D23); short blocat pe paper cu 500 $ (D24) |
| B1 | Date 1 minut + costuri | Gata | faza-b1-date | Antigravity | SIP 2016–2026 + IEX 2020–2026 în cache, validare, costuri (D25), raport SIP vs IEX (`reports/b1_date.md`, D26) |
| B2 | Backtester intraday | Gata | faza-b2-backtester | Claude Code | Motor minut-cu-minut, costuri, sizing, veto FOMC, test aleator, metrici (D27) |
| B3 | D1, D1b, D2 + Poarta 1 B | Gata | faza-b3-strategii | Antigravity | Poarta 1 B = PASS prin D1b (8/8 criterii, Sharpe 1,75, PF 1,60, 9/9 ani > 0, `reports/gate1_daytrading.md`, D30) |
| B4 | Păstrarea stării + AI (învățare zilnică) | Gata | faza-b4-ai-stare | Antigravity | `src/state/store.py`, `meta_label.py`, `daily_learner.py`, `autopsy.py`, `veto.py` (208 teste verzi) |
| B5 | Risk guard intraday + Broker Alpaca Paper | Gata | faza-b5-risc-broker | Antigravity | `src/risk/guard.py` + `src/broker/alpaca_paper.py` (Long+Short+Levier pe 500 $ prin ETF-uri inverse D31, 214 teste verzi) |
| B6a | Dashboard pe date de exemplu (Vercel) | Gata | faza-b6a-dashboard | Antigravity | Next.js în `dashboard/`, date exemplu `tests/fixtures/state/`, live la `https://theo-trading-bot.vercel.app` |
| B6b | Alerte Telegram | Gata | faza-b6b-telegram | Antigravity | `src/alerts/telegram.py`, 185 teste verzi, mesaj de probă livrat pe `@thetheotrading_bot` |
| B6c | Sesiune live paper + resetare dashboard la 500 $ | Gata | faza-b6c-live-demo | Antigravity | `src/live/runner.py`, `src/live/state_writer.py`, `scripts/run_intraday_session.py`, GitHub Actions + branch `state` sincronizat (218 teste verzi) |

| # | Etapă | Status | Branch | Agent | Note |
|---|---|---|---|---|---|
| 0 | Fundația | Gata | main | Antigravity | uv, Python 3.12, pyproject.toml, ruff, pytest, CI verde |
| 1 | Date | Gata | etapa-1-date | Antigravity | Univers S&P 100, cache parquet/csv, drop_incomplete_bar, validate, loader daily & recent |
| 2 | Backtester | Gata | etapa-2-backtester | Claude Code | Indicatori, motor bar-cu-bar, metrici, walk-forward, Monte Carlo, test aleator, detector look-ahead |
| 3 | Strategii + Poarta 1 | Gata | etapa-3-strategii | Claude Code | Poarta 1: FAIL (`reports/gate1.md`); iterația 1, S4 + filtru SPY: FAIL (`reports/gate1_iteratia1.md`) |
| 4 | Risk guard | Oprit | etapa-4-risc | Claude Code | Proiect oprit (D19) |
| 5 | Broker Alpaca paper | Oprit | etapa-5-broker | Claude Code | Proiect oprit (D19) |
| 6 | Stare, veto, post-mortem | Oprit | etapa-6-stare-ai | Antigravity | Proiect oprit (D19) |
| 7 | Rulare zilnică + Telegram | Oprit | etapa-7-rulare | Antigravity + review Claude Code | Proiect oprit (D19) |
| 8 | Dashboard | Oprit | etapa-8-dashboard | Antigravity | Proiect oprit (D19) |
| 9 | Review, Poarta 2, fiscal | Oprit | etapa-9-raportare | Antigravity | Proiect oprit (D19) |
| 10 | Bani reali | Oprit | etapa-10-live | Claude Code | Proiect oprit (D19) |

## Pasul următor exact

**Toate etapele de construcție din Faza B (B0 → B6c) sunt GATA.**
- `src/live/state_writer.py` + `src/live/runner.py`: bucla intraday completă (`run_trading_step`), închiderea și învățarea zilnică la 15:59 ET (`run_end_of_day_learning`), butonul de oprire de urgență (`run_kill_switch`) și sincronizarea în timp real cu branch-ul `state` pe GitHub (`is_sample: False`).
- `scripts/run_intraday_session.py` + `.github/workflows/intraday_paper.yml` + `.github/workflows/kill.yml`: execuție automată în timpul sesiunii SUA (09:30–16:00 ET / 16:30–23:00 ora României), plus butonul `KILL` activ în dashboard-ul Vercel (`218 passed` în pytest).
- Urmează perioada de 3 luni de rulare și învățare pe **Alpaca Paper** (înainte de Poarta 2 B pentru bani reali).

## Pentru proprietar

- Cheile sunt în `.env` (3 noiembrie 2026): Alpaca, Finnhub, Gemini, Telegram, parola dashboard. GH_DISPATCH_TOKEN e și el pus.
- Contul Alpaca: paper „TRADING”, 500 $. `BOT_CAPITAL=500`.
- Decis (4.11.2026, D31): contul paper rămâne la 500 $ (suma reală de după cele 3 luni de probă), dar **activăm ambele direcții (`Long + Short`) și levierul**: pe contul de 500 $ (`< 2.000 $`), semnalele `Short (-1)` pe `SPY`/`QQQ` cumpără automat ETF-urile inverse (`SH`/`SDS` pentru SPY, `PSQ`/`QID` pentru QQQ), iar semnalele `Long (+1)` cumpără `SPY`/`QQQ` (sau `SSO`/`QLD` `2×`). Fără limită la numărul de trade-uri pe zi cât timp trece analiza (`D1b` + `meta_label` + `daily_learner` + `news_veto` + `intraday_guard`).
- Rezultat Poarta 1 B (4.11.2026, D30): **PASS** prin strategia **D1b (`VWAP & Ladder #1`)**, care a trecut toate cele 8/8 criterii (Sharpe OOS 1,75 pe Long-Only și 1,70 cu CAGR 7,06% și 2.982 trade-uri pe Long+Short 2×).
- Dashboard-ul live (`https://theo-trading-bot.vercel.app`) este acum conectat la branch-ul `state` al contului real Alpaca Paper (`500,00 $`, `is_sample: false`), fără bannerul `DATE DE EXEMPLU`.

## Bug-uri cunoscute

Niciunul. 218 de teste pytest trecute offline.

## Ultima actualizare

4 noiembrie 2026 · Antigravity · Faza B completă (B0 → B6c): `src/live/runner.py`, `src/live/state_writer.py`, `scripts/run_intraday_session.py`, GitHub Actions (`intraday_paper.yml`, `kill.yml`), branch-ul `state` inițializat pe contul real Alpaca Paper de 500 $ și dashboard-ul actualizat pe Vercel. 218 teste verzi.
