# Progres Theo Trading Bot

Statusuri: De făcut · În lucru · Gata · Blocat · Oprit

**Proiectul e oprit (D19).** Nicio strategie nu bate SPY ajustat la risc după costuri (Poarta 1), nici după
iterația permisă (D18). Conform D7, nu se trece la paper trading și nici la bani reali.
Proprietarul a pornit apoi **Faza B: day trading SPY/QQQ, doar pe Alpaca Paper** (D20–D22, `docs/PLAN_DAYTRADING.md`).

| # | Faza B | Status | Branch | Agent | Note |
|---|---|---|---|---|---|
| B0 | Broker + cont demo | Gata | faza-b-daytrading | Claude Code | SIP 1 minut de la 2016 (D23); short blocat pe paper cu 500 $ (D24) |
| B1 | Date 1 minut + costuri | De făcut | faza-b1-date | Antigravity | |
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

B0 e gata (D23, D24; `scripts/probe_alpaca_b0.py`, doar citire). Dacă PR-ul `faza-b-daytrading` → `main` nu e
unit, se unește după CI verde. Apoi sub-pasul **B1 (Antigravity)**, branch `faza-b1-date` din `main` actualizat,
după `docs/PLAN_DAYTRADING.md` și D23:
1. Descarcă barele de 1 minut SPY și QQQ, feed SIP, 2016-01-04 → azi (fără ultimele 15 minute), doar sesiunea
   9:30–16:00 ET; cache în `data/` (nu în git), o singură rulare, scriptul în `scripts/`.
2. Validare: zile lipsă față de calendarul NYSE, sesiuni scurte, bare duplicate; teste offline cu un fixture mic.
3. Modelul de costuri din plan (acțiuni SPY/QQQ și CFD US500 0,8 / US100 2,5 puncte) ca funcție pură, cu teste.
4. Diferența SIP vs IEX (VWAP, preț de închidere pe minut) pe 2020-07 → azi, notată în DECISIONS.
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

Niciunul. 118 teste pytest trecute offline.

## Ultima actualizare

3 noiembrie 2026 · Claude Code · Faza B, sub-pasul B0: date Alpaca de 1 minut și short pe paper verificate (D23, D24).
