# Progres Theo Trading Bot

Statusuri: De făcut · În lucru · Gata · Blocat

| # | Etapă | Status | Branch | Agent | Note |
|---|---|---|---|---|---|
| 0 | Fundația | Gata | main | Antigravity | uv, Python 3.12, pyproject.toml, ruff, pytest, CI verde |
| 1 | Date | Gata | etapa-1-date | Antigravity | Univers S&P 100, cache parquet/csv, drop_incomplete_bar, validate, loader daily & recent |
| 2 | Backtester | Gata | etapa-2-backtester | Claude Code | Indicatori, motor bar-cu-bar, metrici, walk-forward, Monte Carlo, test aleator, detector look-ahead |
| 3 | Strategii + Poarta 1 | În lucru | etapa-3-strategii | Claude Code | Poarta 1: FAIL (`reports/gate1.md`); iterația 1 pe S4 (D18) |
| 4 | Risk guard | Blocat | etapa-4-risc | Claude Code | Așteaptă rezultatul iterației 1 (D18) |
| 5 | Broker Alpaca paper | De făcut | etapa-5-broker | Claude Code | |
| 6 | Stare, veto, post-mortem | De făcut | etapa-6-stare-ai | Antigravity | |
| 7 | Rulare zilnică + Telegram | De făcut | etapa-7-rulare | Antigravity + review Claude Code | |
| 8 | Dashboard | De făcut | etapa-8-dashboard | Antigravity | Poate începe pe date de exemplu |
| 9 | Review, Poarta 2, fiscal | De făcut | etapa-9-raportare | Antigravity | |
| 10 | Bani reali | Blocat | etapa-10-live | Claude Code | Doar după Poarta 2 și `LIVE_APPROVED.md` |

## Pasul următor exact

Etapa 3 (Claude Code), pe `etapa-3-strategii`; PR #3 spre `main` rămâne deschis până la finalul iterației.
Poarta 1 de bază: FAIL pentru S1–S4 (`reports/gate1.md`, rămâne ca referință). Proprietarul a cerut o iterație și a
lăsat alegerea agentului: **D18**, S4 + filtrul SPY > SMA(200). Sub-pasul **3c (următorul)**:
1. `src/strategies/s4_macd_ema200.py`: parametru nou `spy_filter: int`; intrarea cere în plus
   `benchmark_uptrend(spy, df.index, params.spy_filter)` (din `common.py`, ca la S1/S3); motivul intrării
   pomenește filtrul; docstring-ul notează D18. `config/strategies.yaml`: S4 `spy_filter: 200`. Teste în
   `tests/test_strategies.py`: S4 cere SPY, iar SPY sub SMA blochează intrările. Nimic altceva nu se schimbă.
2. `scripts/gate1.py`: opțiune de a rula doar S4 și de a scrie `reports/gate1_iteratia1.md` (+ grafice și JSON cu
   același sufix), fără să suprascrie `reports/gate1.md`. Aceleași 7 criterii, ambele variante, 500 aleatoare,
   ±20% (include `spy_filter` 160/240). Datele sunt în `data/cache/`; rularea ~5 min, în fundal, log în `.cache/`.
3. `scripts/check.sh`, PROGRESS, commit, push; corpul PR #3 actualizat cu rezultatul; unire după CI verde.
4. Regula de oprire (D18): dacă S4 cu filtru pică, **proiectul se oprește** (nicio altă iterație). Dacă trece,
   urmează etapa 4, iar PASS-ul se confirmă doar la Poarta 2.

## Pentru proprietar

- Cheile sunt în `.env` (3 noiembrie 2026): Alpaca, Finnhub, Gemini, Telegram, parola dashboard. GH_DISPATCH_TOKEN e și el pus.
- Contul Alpaca: paper „TRADING”, 500 $. `BOT_CAPITAL=500`.
- Decis (3.11.2026): Poarta 1 se rulează în ambele variante, fracționare și acțiuni întregi (D15).
- Decis (3.11.2026): după Poarta 1 = FAIL, o singură iterație, aleasă de agent: S4 + filtru SPY (D18). Dacă pică, ne oprim.

## Bug-uri cunoscute

Niciunul. 116 teste pytest trecute offline.

## Ultima actualizare

3 noiembrie 2026 · Claude Code · Etapa 3b (Poarta 1) finalizată: FAIL pentru S1–S4; iterația 1 decisă (D18).
