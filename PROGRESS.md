# Progres Theo Trading Bot

Statusuri: De făcut · În lucru · Gata · Blocat

| # | Etapă | Status | Branch | Agent | Note |
|---|---|---|---|---|---|
| 0 | Fundația | Gata | main | Antigravity | uv, Python 3.12, pyproject.toml, ruff, pytest, CI verde |
| 1 | Date | Gata | etapa-1-date | Antigravity | Univers S&P 100, cache parquet/csv, drop_incomplete_bar, validate, loader daily & recent |
| 2 | Backtester | Gata | etapa-2-backtester | Claude Code | Indicatori, motor bar-cu-bar, metrici, walk-forward, Monte Carlo, test aleator, detector look-ahead |
| 3 | Strategii + Poarta 1 | Gata | etapa-3-strategii | Claude Code | Poarta 1: FAIL, nicio strategie nu trece (`reports/gate1.md`) |
| 4 | Risk guard | Blocat | etapa-4-risc | Claude Code | Așteaptă decizia proprietarului după Poarta 1 |
| 5 | Broker Alpaca paper | De făcut | etapa-5-broker | Claude Code | |
| 6 | Stare, veto, post-mortem | De făcut | etapa-6-stare-ai | Antigravity | |
| 7 | Rulare zilnică + Telegram | De făcut | etapa-7-rulare | Antigravity + review Claude Code | |
| 8 | Dashboard | De făcut | etapa-8-dashboard | Antigravity | Poate începe pe date de exemplu |
| 9 | Review, Poarta 2, fiscal | De făcut | etapa-9-raportare | Antigravity | |
| 10 | Bani reali | Blocat | etapa-10-live | Claude Code | Doar după Poarta 2 și `LIVE_APPROVED.md` |

## Pasul următor exact

Etapa 3 e gata pe `etapa-3-strategii` (3a strategiile, 3b Poarta 1); PR spre `main`.
**Poarta 1: nicio strategie nu trece**, în nicio variantă (`reports/gate1.md`). Toate pică criteriul 2: Sharpe OOS
0.60–0.75 față de 0.85 la SPY (prag 1.05); 500 $ din 2009 → 1.195 $ cu S1, 5.563 $ cu SPY. S3 pierde bani.
Conform planului (D7) ne oprim: **nu se începe etapa 4** până nu decide proprietarul:
- fie oprim proiectul aici;
- fie aprobă o iterație documentată (maximum 2 per strategie, interdicția 6): motivul se scrie în
  `docs/DECISIONS.md` ÎNAINTE de rulare, apoi `scripts/gate1.py` din nou (datele sunt în `data/cache/`;
  `PYTHONPATH=. uv run python scripts/download_history.py` le reface). NU se ajustează parametrii după rezultate.

## Pentru proprietar

- Cheile sunt în `.env` (3 noiembrie 2026): Alpaca, Finnhub, Gemini, Telegram, parola dashboard. GH_DISPATCH_TOKEN e și el pus.
- Contul Alpaca: paper „TRADING”, 500 $. `BOT_CAPITAL=500`.
- Decis (3.11.2026): Poarta 1 se rulează în ambele variante, fracționare și acțiuni întregi (D15).
- **De decis:** după Poarta 1 = FAIL, oprim proiectul sau încercăm o iterație documentată?

## Bug-uri cunoscute

Niciunul. 116 teste pytest trecute offline.

## Ultima actualizare

3 noiembrie 2026 · Claude Code · Etapa 3b (Poarta 1) finalizată: FAIL pentru S1–S4.
