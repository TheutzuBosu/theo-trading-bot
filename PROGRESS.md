# Progres Theo Trading Bot

Statusuri: De făcut · În lucru · Gata · Blocat · Oprit

**Proiectul e oprit (D19).** Nicio strategie nu bate SPY ajustat la risc după costuri (Poarta 1), nici după
iterația permisă (D18). Conform D7, nu se trece la paper trading și nici la bani reali.
Proprietarul a pornit apoi **Faza B: day trading SPY/QQQ, doar pe Alpaca Paper** (D20–D22, `docs/PLAN_DAYTRADING.md`).

| # | Faza B | Status | Branch | Agent | Note |
|---|---|---|---|---|---|
| B0 | Broker + cont demo | Gata | faza-b-daytrading | Claude Code | SIP 1 minut de la 2016 (D23); short blocat pe paper cu 500 $ (D24) |
| B1 | Date 1 minut + costuri | Gata | faza-b1-date | Antigravity | SIP 2016–2026 + IEX 2020–2026 în cache, validare, costuri (D25), raport SIP vs IEX (`reports/b1_date.md`, D26) |
| B2 | Backtester intraday | Gata | faza-b2-backtester | Claude Code | Motor minut-cu-minut, costuri, sizing, veto FOMC, test aleator, metrici (D27); PR deschis |
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

B2 e gata (D27): `src/backtest/intraday_engine.py` (`IntradayPanel`, `IntradaySignals`, `IntradayConfig`,
`run_intraday`), `src/backtest/fomc.py` (veto ±30 min), `src/backtest/intraday_metrics.py` (`summarize_intraday`,
`r_stats`, `deflated_sharpe`, `direction_outcomes`, `random_direction_test`); detectorul de look-ahead primește
`columns=SIGNAL_COLUMNS` pentru semnale de 1 minut. Dacă PR-ul `faza-b2-backtester` → `main` (#6) nu e unit, se unește
după CI verde: asta o poate face și Antigravity (4.11.2026, Claude e la limită). B3 rămâne DOAR Claude Code:
după unire, Antigravity se oprește și se așteaptă Claude (în Faza B nu există altă etapă Antigravity deblocată). Apoi sub-pasul **B3 (Claude Code)**, branch `faza-b3-strategii` din `main` actualizat, după
`docs/PLAN_DAYTRADING.md` și D24–D27:
1. Înainte de orice rulare, în `docs/DECISIONS.md` (D28): Poarta 1 B fixată pe varianta long-only (`long_only=True`,
   `max_exposure=1.0`, fără marjă, D24), testul aleator long-only (candidații din rularea long+short), N = 9,
   parametrii D1b din paper-ul Maróy 2025 și cei ≤ 2 parametri recalibrați lunar (fereastră de 2 ani) pentru fiecare.
2. `src/strategies/` intraday: D1 (Zarattini, Aziz & Barbon 2024: banda de zgomot din 14 zile, verificări la :00/:30,
   stop trailing bandă/VWAP, sizing după volatilitate), D1b (aceeași intrare, ieșire VWAP & Ladder) și D2 (ORB 5
   minute, martor). Funcții pure care întorc cadre cu `SIGNAL_COLUMNS` + `entry_reason`; test de look-ahead pe
   fixture-ul de 1 minut. Regulile se iau din PDF-urile paper-elor (citează secțiunile).
3. Walk-forward lunar (doar OOS înlănțuit), costuri `stock` și `cfd` + stres ×1,5, verificarea pe IEX 2020–2026 (D26),
   apoi raportul `reports/gate1_daytrading.md` cu toate cele 7 criterii. Dacă nu trec toate: Faza B se oprește.

## Pentru proprietar

- Cheile sunt în `.env` (3 noiembrie 2026): Alpaca, Finnhub, Gemini, Telegram, parola dashboard. GH_DISPATCH_TOKEN e și el pus.
- Contul Alpaca: paper „TRADING”, 500 $. `BOT_CAPITAL=500`. Botul nu a plasat niciun ordin și nu va plasa.
- Decis (3.11.2026): Poarta 1 se rulează în ambele variante, fracționare și acțiuni întregi (D15).
- Decis (3.11.2026): după Poarta 1 = FAIL, o singură iterație, aleasă de agent: S4 + filtru SPY (D18). Dacă pică, ne oprim.
- Rezultat (3.11.2026): iterația 1 a picat (D19), deci Faza A s-a oprit. Proprietarul a pornit Faza B (D20–D22).
- Decis (3.11.2026, D24): contul paper rămâne la 500 $. Short-ul și levierul nu sunt permise sub 2.000 $, deci
  demo-ul rulează doar long, fără levier. Poarta 1 B se judecă pe varianta long-only (fixată în B3 înainte de rulare).

## Bug-uri cunoscute

Niciunul. 176 de teste pytest trecute offline.

## Ultima actualizare

3 noiembrie 2026 · Claude Code · Faza B, sub-pasul B2 gata: backtester intraday minut-cu-minut, veto FOMC, test cu direcție aleatoare corectat, metrici Poarta 1 B (D27).
