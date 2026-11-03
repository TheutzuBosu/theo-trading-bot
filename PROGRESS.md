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
| B3 | D1, D1b, D2 + Poarta 1 B | În lucru | faza-b3-strategii | Antigravity | B3.1 + B3.2 gata (`intraday_d1.py`, `intraday_d2.py`, extensii motor, 194 teste verzi); urmează B3.3 (`reports/gate1_daytrading.md`) |
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

**B3.2 e gata.** Motorul intraday (`src/backtest/intraday_engine.py`) suportă acum `exit_long`, `exit_short` și
`stop_after_target`; strategiile D1 și D1b sunt în `src/strategies/intraday_d1.py`, iar D2 (ORB 5m) e în
`src/strategies/intraday_d2.py`. Toate testele unitare și de look-ahead din `tests/test_intraday_strategies.py` și
`tests/test_intraday_engine.py` sunt verzi (`194 passed`).

Sub-pasul următor, **B3.3**, pe branch-ul `faza-b3-strategii`:
1. Scrie scriptul / modulul de evaluare pentru Poarta 1 B (ex. `src/backtest/gate1_daytrading.py` + `scripts/run_gate1_daytrading.py`):
   - **D1 calibrat lunar (walk-forward)**: la începutul fiecărei luni OOS (`2018-01-02 .. 2026-10-30`), alege perechea `(L, m)` din grila `L ∈ {7, 10, 14, 20, 28}` × `m ∈ {0.75, 1.0, 1.25, 1.5}` cu Sharpe net maxim pe ultimele 24 luni anterioare (long-only, portofoliu 50/50 SPY+QQQ; tie-breaker mai aproape de `(14, 1.0)`).
   - **Rulări OOS `2018-01-02 .. 2026-10-30`** (atât `long-only` 1x cât și `long+short` informativ, pe `SPY`, `QQQ` și `50/50 SPY+QQQ`): D1 default `(14, 1.0)`, D1 calibrat lunar, D1b (`VWAP & Ladder #1`), D2 (`ORB 5m`), și buy & hold SPY / 50-50.
   - **Verificare cele 7 criterii din D29 + condiția D29b**: (1) Sharpe net >= max(1.0, Sharpe B&H + 0.20), (2) DSR >= 0.95 cu `N = 9`, (3) MaxDD <= 15%, (4) >= 500 tranzacții și >= 40/an în fiecare an complet 2018–2025, (5) `test_random_direction` (B = 1000, p < 0.05), (6) stabilitate ±20% pe `L`, `m` și `target_r`/`ladder_r` (toți vecinii profitabili și Sharpe >= 70% din centru), (7) verificare pe datele IEX `2020-08-03 .. 2026-10-30` (profitabil, Sharpe IEX >= 70% din SIP pe aceeași fereastră), și pentru D1b: expectancy netă > 0 pe `2024-10-01 .. 2026-10-30`.
2. Generează `reports/gate1_daytrading.md` și înregistrează verdictul în `docs/DECISIONS.md` (`D30`).
3. Deschide PR `faza-b3-strategii -> main`, fă merge, și setează pasul următor **B4** (păstrarea stării + `autopsy.py` + `daily_learner.py` + `meta_label.py`, conform deciziei proprietarului de a duce botul complet până la capăt pe Alpaca Paper).

## Pentru proprietar

- Cheile sunt în `.env` (3 noiembrie 2026): Alpaca, Finnhub, Gemini, Telegram, parola dashboard. GH_DISPATCH_TOKEN e și el pus.
- Contul Alpaca: paper „TRADING”, 500 $. `BOT_CAPITAL=500`.
- Decis (3.11.2026, D24): contul paper rămâne la 500 $. Short-ul și levierul nu sunt permise sub 2.000 $, deci demo-ul rulează doar long, fără levier. Poarta 1 B se judecă pe varianta long-only (D29).
- Decis (4.11.2026): indiferent de scorul Porții 1 B pe backtest, construim botul complet pe **Alpaca Paper** până la capăt (`B3 -> B4 -> B5 -> B6c`), fără limită zilnică la numărul de trade-uri, cu învățare zilnică din greșeli și deploy automat în Git și Vercel după fiecare etapă. Doar banii reali rămân blocați de Poarta 2.

## Bug-uri cunoscute

Niciunul. 194 de teste pytest trecute offline.

## Ultima actualizare

4 noiembrie 2026 · Antigravity · Faza B, sub-pasul B3.2 gata: extensii `intraday_engine.py` (`exit_long`, `exit_short`, `stop_after_target`), strategii `intraday_d1.py` (D1 + D1b) și `intraday_d2.py` (D2 ORB 5m), 194 teste verzi + ghid complet `docs/GHID_EXECUTIE_AGENTI.md`. Urmează B3.3 (evaluarea OOS + `reports/gate1_daytrading.md`).
