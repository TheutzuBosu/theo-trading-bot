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
| B6d | Audit + reparații execuție live (D32) | Gata | faza-b6d-audit-live | Claude Code | Ordine Alpaca reale (market + stop), preț ETF corect, rulări la orele D1b, stare restaurată din branch-ul `state`, ieșiri D1b live, învățare din tranzacțiile închise (234 teste verzi) |
| B6e | Scanner toată piața SUA (Pre-Market & Intraday, D33) | Gata | main | Antigravity | `src/ai/market_scanner.py` + `src/ai/premarket.py` + `evaluate_mover_candidate` în `runner.py`: scanează și tranzacționează orice acțiune SUA în mișcare (mize 5 $ – 35 $, Risc:Reward 1:3 – 1:10, Long + Short + Levier) + afișare în Dashboard și Telegram |
| B6f | Reparații critice după auditul independent (D34) | Gata | faza-b6f-reparatii-critice | Claude Code | Un singur motor (lacăt `engine_lock.json`), fereastra NYSE + releu sigur, poziții fără stop închise, stop ancorat pe fill, short doar pe ETF invers dedicat, scanner fail-closed, KILL care oprește botul direct, `/api/cron` protejat (268 teste verzi) |

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

**B7: monitorizarea pe Alpaca Paper (12 săptămâni) + Poarta 2.** Construcția e gata (B0 → B6f, D34).
- Cum rulează acum: în zilele NYSE, un lanț de rulări de 15 minute (`intraday_paper.yml`, mod `session`) de la 09:00 ET
  până la închidere + 5 min; fiecare rulare face cicluri de 60 s (`scripts/run_intraday_session.py --duration-minutes 15`)
  și pornește singură următoarea (`--should-relay`). Între 08:00 și 09:00 ET doar briefing Pre-Market (~2 min, fără lanț).
  Pornire: cron GitHub (12–14 UTC la 20 min, 15–20 UTC la 15 min), Vercel Cron (13:00 și 14:00 UTC), auto-wake din dashboard.
- Verificări zilnice în prima săptămână (fără cod nou):
  1. `gh run list --workflow intraday_paper.yml --limit 40` → rulări „success” legate între ele, fără găuri > 20 min.
  2. `git fetch origin state && git show origin/state:state/engine_lock.json` → `holder` = `gha-<run_id>-1` în timpul
     sesiunii, gol după închidere.
  3. `git show origin/state:state/live_journal.json` (`open_trades`, `last_eod_date`) și `trades.csv`; orice poziție la
     Alpaca trebuie să aibă un ordin STOP (`protect_orphan_positions` închide altfel și trimite alertă Telegram).
- Orice eroare nouă se repară cu test în `tests/test_b6f_fixes.py` (lacăt, fereastră, scanner) sau
  `tests/test_live_audit.py` (execuție), comanda: `uv run pytest tests/test_b6f_fixes.py -q`, apoi `bash scripts/check.sh`.
- **Înainte de 1 ianuarie 2027:** adaugă datele FOMC 2027 în `src/backtest/fomc.py` (`SCHEDULED[2027]`, de pe
  federalreserve.gov/monetarypolicy/fomccalendars.htm) + test; fără ele, veto-ul FOMC nu mai blochează nimic în 2027.
- Raportul Poarta 2 B (`reports/gate2_daytrading.md`) se scrie după 12 săptămâni, din `state/trades.csv`.

## Pentru proprietar

- Cheile sunt în `.env` (3 noiembrie 2026): Alpaca, Finnhub, Gemini, Telegram, parola dashboard. GH_DISPATCH_TOKEN e și el pus.
- Contul Alpaca: paper „TRADING”, 500 $. `BOT_CAPITAL=500`.
- Decis (4.11.2026, D31): contul paper rămâne la 500 $ (suma reală de după cele 3 luni de probă), dar **activăm ambele direcții (`Long + Short`) și levierul**: pe contul de 500 $ (`< 2.000 $`), semnalele `Short (-1)` pe `SPY`/`QQQ` cumpără automat ETF-urile inverse (`SH`/`SDS` pentru SPY, `PSQ`/`QID` pentru QQQ), iar semnalele `Long (+1)` cumpără `SPY`/`QQQ` (sau `SSO`/`QLD` `2×`). Fără limită la numărul de trade-uri pe zi cât timp trece analiza (`D1b` + `meta_label` + `daily_learner` + `news_veto` + `intraday_guard`).
- Rezultat Poarta 1 B (4.11.2026, D30): **PASS** prin strategia **D1b (`VWAP & Ladder #1`)**, care a trecut toate cele 8/8 criterii (Sharpe OOS 1,75 pe Long-Only și 1,70 cu CAGR 7,06% și 2.982 trade-uri pe Long+Short 2×).
- Dashboard-ul live (`https://theo-trading-bot.vercel.app`) este acum conectat la branch-ul `state` al contului real Alpaca Paper (`500,00 $`, `is_sample: false`), fără bannerul `DATE DE EXEMPLU`.
- Decis (8.11.2026, D35): universul deschis de acțiuni SUA (scanner D33) aprobat, cu filtrele B6f; rolul dual al lui
  Gemini (doar filtru pe D1b, propune intrări pe scanner, totul prin `guard.py`); repo public → minute GitHub
  nelimitate; `CRON_SECRET` pus în Vercel.
- Decis (8.11.2026, D36): pragul minim de preț la scanner e `2 $` (nu 5 $), ca vineri 6.11 (GOGO, QNTU, FLYT).
- După un KILL, botul rămâne oprit până îl repornești tu: GitHub → Actions → „Intraday Paper Session” → Run
  workflow → mode `reset-kill`.

## Bug-uri cunoscute

Niciunul deschis după B6f (268 teste offline); cele 3 decizii din D34 sunt rezolvate de proprietar în D35.
Rămâne de actualizat `AGENTS.md` (Regula 7 + scopul D33) conform D35 — modificarea trebuie aprobată direct de
proprietar (fișierul de reguli al agenților).
Limită asumată: stop-ul se mută doar la cicluri (60 s), nu la fiecare tick.

## Ultima actualizare

8 noiembrie 2026 · Claude Code · D36: pragul minim de preț la scanner coborât la 2 $ (decizia proprietarului). D35: aprobările proprietarului (univers deschis, rolul dual Gemini, repo public, `CRON_SECRET`). 269 teste verzi.
