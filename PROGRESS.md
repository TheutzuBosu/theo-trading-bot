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
| B3 | D1, D1b, D2 + Poarta 1 B | În lucru | faza-b3-strategii | Claude Code | B3.1 gata: D29 (Poarta 1 B, reguli D1/D2) pre-înregistrat; parametrii D1b așteaptă PDF-ul Maróy |
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

**B3.1 e gata: D29 din `docs/DECISIONS.md` fixează, înainte de orice rulare, Poarta 1 B (long-only, 7 criterii,
N = 9, OOS 2018-01 → 2026-10), regulile D1 și D2 (din paper-e și din codul publicat de autori), calibrarea lunară D1
(L și m) și stop-ul la broker = LB.** Lipsesc doar parametrii D1b: PDF-ul Maróy 2025 (SSRN 5095349) e blocat pentru
agent (verificare anti-bot SSRN, ResearchGate cu plată), deci îl descarcă proprietarul (vezi „Pentru proprietar”).

Sub-pasul următor, **B3.2 (DOAR Claude Code)**, pe branch-ul `faza-b3-strategii`:
1. Dacă există `~/Downloads/maroy2025.pdf` (sau alt PDF Maróy în `~/Downloads`): îl copiezi în `.cache/papers/`
   (nu în git), citești secțiunile cu ieșirile și rezultatele optimizării și scrii **D29b** cu parametrii D1b
   (L, m, frecvența verificărilor, pragul „Ladder”, cum se definește revenirea la VWAP), cu secțiunile citate.
   Dacă PDF-ul lipsește, faci punctele 2–3 doar pentru D1 și D2; D1b așteaptă (fără rulări D1b).
2. `src/strategies/intraday_d1.py` și `intraday_d2.py` (funcții pure, cadre cu `SIGNAL_COLUMNS` + `entry_reason`),
   exact după D29: banda de zgomot, VWAP din `vwap`·`volume`, verificări pe barele 9:59, 10:29 … 15:29, sizing,
   stop = LB. Ieșirea D1 depinde de direcție: adaugi în motor coloanele opționale `exit_long` / `exit_short`
   (`exit` rămâne pentru ambele) și verifici că un flip (ieșire + intrare inversă la același Open) merge.
3. Teste offline în `tests/`: reguli pe date sintetice mici (banda, verificări, doji, țintă 10R, sizing) și testul
   de look-ahead (`src/backtest/lookahead.py`, `columns=SIGNAL_COLUMNS`) pe fixture-ul de 1 minut.
   Apoi `scripts/check_fast.sh`, `PROGRESS.md`, commit, push.

După B3.2: **B3.3** walk-forward lunar + rulările OOS + testul aleator + ±20% + IEX, apoi `reports/gate1_daytrading.md`
cu toate cele 7 criterii din D29. Dacă nu trec toate: Faza B se oprește.

## Pentru proprietar

- Cheile sunt în `.env` (3 noiembrie 2026): Alpaca, Finnhub, Gemini, Telegram, parola dashboard. GH_DISPATCH_TOKEN e și el pus.
- Contul Alpaca: paper „TRADING”, 500 $. `BOT_CAPITAL=500`. Botul nu a plasat niciun ordin și nu va plasa.
- Decis (3.11.2026): Poarta 1 se rulează în ambele variante, fracționare și acțiuni întregi (D15).
- Decis (3.11.2026): după Poarta 1 = FAIL, o singură iterație, aleasă de agent: S4 + filtru SPY (D18). Dacă pică, ne oprim.
- Rezultat (3.11.2026): iterația 1 a picat (D19), deci Faza A s-a oprit. Proprietarul a pornit Faza B (D20–D22).
- Decis (3.11.2026, D24): contul paper rămâne la 500 $. Short-ul și levierul nu sunt permise sub 2.000 $, deci
  demo-ul rulează doar long, fără levier. Poarta 1 B se judecă pe varianta long-only (fixată în B3 înainte de rulare).
- **De făcut (4.11.2026): descarcă paper-ul Maróy pentru D1b.** Agentul nu-l poate lua singur (SSRN cere verificare
  „nu sunt robot”). Pașii:
  1. Deschide în Chrome: https://papers.ssrn.com/sol3/papers.cfm?abstract_id=5095349
  2. Dacă apare „Verify you are human”, bifează căsuța.
  3. Apasă butonul albastru „Download This Paper”. Dacă cere cont SSRN, fă-ți unul gratuit (sau intră cu Google).
  4. Fișierul ajunge în folderul Downloads. Redenumește-l `maroy2025.pdf` (click dreapta → Rename).
  Dacă nu reușești, spune-i agentului: D1b se abandonează (D29), iar D1 și D2 merg mai departe.

## Bug-uri cunoscute

Niciunul. 185 de teste pytest trecute offline.

## Ultima actualizare

4 noiembrie 2026 · Claude Code · Faza B, sub-pasul B3.1 gata: D29 (Poarta 1 B, reguli D1/D2, calibrare, stop la broker) pre-înregistrat în `docs/DECISIONS.md`. Urmează B3.2 (strategiile în cod); D1b așteaptă PDF-ul Maróy.
