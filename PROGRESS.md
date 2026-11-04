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
| B4 | Păstrarea stării + AI (învățare zilnică) | În lucru | faza-b4-ai-stare | Orice agent | Starea în `state/`, `autopsy.py`, `daily_learner.py`, `meta_label.py`, `news_veto.py` |
| B6a | Dashboard pe date de exemplu (Vercel) | Gata | faza-b6a-dashboard | Antigravity | Next.js în `dashboard/`, date exemplu `tests/fixtures/state/`, live la `https://theo-trading-bot.vercel.app` |
| B6b | Alerte Telegram | Gata | faza-b6b-telegram | Antigravity | `src/alerts/telegram.py`, 185 teste verzi, mesaj de probă livrat pe `@thetheotrading_bot` |

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

**B3 e gata (Poarta 1 B = PASS prin D1b, `reports/gate1_daytrading.md`, D30).**
- **D1b (`VWAP & Ladder #1`, Maróy 2025)** a trecut toate cele **8/8** criterii pre-înregistrate pe OOS `2018-01-02 → 2026-10-30` (Long-Only, SPY + QQQ): 1.399 tranzacții, Profit Factor 1,60, E[R] = +0,3034R (`t = 5,79`), E[R] la costuri ×1,5 = +0,2783R, DSR = 99,9%, test direcție aleatoare 100,0%, 9/9 ani calendaristici pe plus (cel mai slab +0,3%), Sharpe 1,75, MaxDD 1,90%, 18/18 perturbații ±20% pozitive, și E[R] = +0,0668R > 0 pe fereastra nevăzută de autor (`2024-10-01 → 2026-10-30`). Pe IEX păstrează 91,6% din expectancy-ul SIP.
- **D1 default (`L = 14, m = 1,0`)** a trecut 6/7 criterii (Sharpe 1,18, PF 1,33, 8/9 ani pe plus, MaxDD 2,86%, t = 4,12) și rămâne în cod ca referință.

Sub-pasul următor, **B4**, pe branch-ul nou `faza-b4-ai-stare` (creat din `main`):
1. **`src/state/store.py`**:
   - Scriere și citire atomică (prin fișier `.tmp` + `os.replace`) pentru fișierele din `state/` (cu schema identică cu `tests/fixtures/state/` și `dashboard/src/lib/types.ts`):
     `state/positions.json`, `state/orders.json`, `state/equity.csv`, `state/trades.csv`, `state/daily_report.json`, `state/kill_switch.json`, `state/autopsies.jsonl`, `state/learned_rules.json`.
   - Funcție de reconciliere la pornire între pozițiile/ordinul stop de la broker și `state/positions.json` (adevărul la neconcordanță = brokerul).
2. **Învățarea zilnică din greșeli (`src/ai/`)**:
   - `src/ai/autopsy.py`: după fiecare poziție închisă, salvează un rând JSONL în `state/autopsies.jsonl` cu contextul intrării (simbol, strategie D1b/D1, direcție, ora, distanța față de UB și VWAP, `sigma_d`, `r_multiple`, `pnl`, `mfe`, `mae`, motiv ieșire, etichetă mecanică + explicație Gemini opțională cu fallback mecanic dacă API-ul nu răspunde).
   - `src/ai/daily_learner.py`: la finalul sesiunii (după 16:00 ET), analizează `state/trades.csv` + `state/autopsies.jsonl` pe fereastra mobilă și actualizează `state/learned_rules.json` (penalizare de mărime `size_multiplier` între `0.5` și `1.0` pe ore/condiții cu expectancy negativ, plus sumarul lecțiilor zilei în `state/daily_report.json` pentru dashboard).
   - `src/ai/meta_label.py`: model logistic simplu (`scikit-learn` / `numpy`) antrenat strict pe tranzacțiile anterioare (`min_trades=100`, doar în modul `paper_Shadow` / scalare mărime, niciodată nu falsifică stop-ul sau regulile de risc).
   - `src/ai/news_veto.py`: interogare Finnhub + Gemini înainte de intrare cu timeout scurt (3s) și fallback `allow=True` dacă API-ul e indisponibil, blocând doar la știre catastrofală / halt pe simbol.
3. **Teste offline în `tests/test_state_and_ai.py`** (fără apeluri reale de rețea — mock pentru Gemini/Finnhub), verificare `bash scripts/check_fast.sh`, merge în `main` și deploy în Vercel (`bash scripts/deploy_dashboard.sh`).

## Pentru proprietar

- Cheile sunt în `.env` (3 noiembrie 2026): Alpaca, Finnhub, Gemini, Telegram, parola dashboard. GH_DISPATCH_TOKEN e și el pus.
- Contul Alpaca: paper „TRADING”, 500 $. `BOT_CAPITAL=500`.
- Decis (4.11.2026, D31): contul paper rămâne la 500 $ (suma reală de după cele 3 luni de probă), dar **activăm ambele direcții (`Long + Short`) și levierul**: pe contul de 500 $ (`< 2.000 $`), semnalele `Short (-1)` pe `SPY`/`QQQ` cumpără automat ETF-urile inverse (`SH`/`SDS` pentru SPY, `PSQ`/`QID` pentru QQQ), iar semnalele `Long (+1)` cumpără `SPY`/`QQQ` (sau `SSO`/`QLD` `2×`). Fără limită la numărul de trade-uri pe zi cât timp trece analiza (`D1b` + `meta_label` + `daily_learner` + `news_veto` + `intraday_guard`).
- Rezultat Poarta 1 B (4.11.2026, D30): **PASS** prin strategia **D1b (`VWAP & Ladder #1`)**, care a trecut toate cele 8/8 criterii (Sharpe OOS 1,75 pe Long-Only și 1,70 cu CAGR 7,06% și 2.982 trade-uri pe Long+Short 2×).
- Decis (4.11.2026): construim botul complet pe **Alpaca Paper** până la capăt (`B3 -> B4 -> B5 -> B6c`), fără limită zilnică la numărul de trade-uri, cu învățare zilnică din greșeli și deploy automat în Git și Vercel după fiecare etapă. Doar banii reali rămân blocați de Poarta 2.

## Bug-uri cunoscute

Niciunul. 198 de teste pytest trecute offline.

## Ultima actualizare

4 noiembrie 2026 · Antigravity · Faza B, etapa B3 gata: Poarta 1 B = PASS prin D1b (8/8 criterii, `reports/gate1_daytrading.md`, D30). Urmează B4 (păstrarea stării + învățarea zilnică din greșeli în `src/state/` și `src/ai/`).
