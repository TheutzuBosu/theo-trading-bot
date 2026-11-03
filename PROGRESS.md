# Progres Theo Trading Bot

Statusuri: De făcut · În lucru · Gata · Blocat · Oprit

**Proiectul e oprit (D19).** Nicio strategie nu bate SPY ajustat la risc după costuri (Poarta 1), nici după
iterația permisă (D18). Conform D7, nu se trece la paper trading și nici la bani reali.
Proprietarul a pornit apoi **Faza B: day trading SPY/QQQ, doar pe Alpaca Paper** (D20–D22, `docs/PLAN_DAYTRADING.md`).

| # | Faza B | Status | Branch | Agent | Note |
|---|---|---|---|---|---|
| B0 | Broker + cont demo | Gata | faza-b-daytrading | Claude Code | SIP 1 minut de la 2016 (D23); short blocat pe paper cu 500 $ (D24) |
| B1 | Date 1 minut + costuri | În lucru | faza-b1-date | Antigravity | Cod + teste gata (D25); date descărcate; lipsesc raportul SIP vs IEX și D26 |
| B2 | Backtester intraday | De făcut | faza-b2-backtester | Claude Code | |
| B3 | D1, D1b, D2 + Poarta 1 B | De făcut | faza-b3-strategii | Claude Code | |

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

B0 e unit în `main` (PR #4). **B1 (Antigravity)**, branch `faza-b1-date` (există pe GitHub), după
`docs/PLAN_DAYTRADING.md`, D23 și D25. Gata și urcat: `src/data/intraday.py` (calendar NYSE, filtru sesiune,
descărcare Alpaca, cache), `src/data/intraday_validation.py`, `src/data/feed_compare.py` (SIP vs IEX),
`src/backtest/intraday_costs.py` (costuri acțiuni + CFD), scripturile `scripts/download_minute.py` și
`scripts/b1_data_report.py`, testele `tests/test_intraday*.py` (143 trecute). Ce lipsește:
1. Descărcarea e **gata** (3.11.2026, până la 2026-11-02, SIP + IEX, SPY + QQQ, în `data/cache/minute/`;
   rezumat în `.cache/download_minute.json`). Nu se mai rulează.
2. Rulează `PYTHONPATH=. uv run python scripts/b1_data_report.py` → `reports/b1_date.md` (validare + SIP vs IEX).
   Dacă apar zile lipsă sau sesiuni incomplete, verifică dacă sunt închideri reale (ex. 9.01.2025, doliu național
   Carter) sau goluri Alpaca, și notează-le.
3. Scrie D26 în `docs/DECISIONS.md`: rezultatul validării și diferența SIP vs IEX (VWAP de sesiune, închidere pe
   minut, acoperire, volum) și dacă VWAP-ul IEX e folosibil live pentru D1 (de ex. diferență mediană ≪ costul de
   0,015 $/parte, adică ~0,25 pb la 600 $).
4. `scripts/check.sh`, PROGRESS (B1 = Gata), commit, push, PR `faza-b1-date` → `main`, unit după CI verde.
Fără cod de strategie în B1. Apoi B2 (Claude Code).

## Pentru proprietar

- Cheile sunt în `.env` (3 noiembrie 2026): Alpaca, Finnhub, Gemini, Telegram, parola dashboard. GH_DISPATCH_TOKEN e și el pus.
- Contul Alpaca: paper „TRADING”, 500 $. `BOT_CAPITAL=500`. Botul nu a plasat niciun ordin și nu va plasa.
- Decis (3.11.2026): Poarta 1 se rulează în ambele variante, fracționare și acțiuni întregi (D15).
- Decis (3.11.2026): după Poarta 1 = FAIL, o singură iterație, aleasă de agent: S4 + filtru SPY (D18). Dacă pică, ne oprim.
- Rezultat (3.11.2026): iterația 1 a picat (D19), deci Faza A s-a oprit. Proprietarul a pornit Faza B (D20–D22).
- Decis (3.11.2026, D24): contul paper rămâne la 500 $. Short-ul și levierul nu sunt permise sub 2.000 $, deci
  demo-ul rulează doar long, fără levier. Poarta 1 B se judecă pe varianta long-only (fixată în B3 înainte de rulare).

## Bug-uri cunoscute

Niciunul. 143 de teste pytest trecute offline.

## Ultima actualizare

3 noiembrie 2026 · Antigravity · Faza B, sub-pasul B1: cod date 1 minut, validare, costuri (D25); descărcarea în curs.
