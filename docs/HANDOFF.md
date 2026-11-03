# Handoff Theo Trading Bot

## Ultima actualizare
- **Data:** 3 noiembrie 2026
- **Etapă finalizată:** Etapa 3a — strategiile S1–S4 (etapa 2, backtesterul, e unită în `main` prin PR #2)
- **Branch:** `etapa-3-strategii`
- **Agent:** Claude Code

## Ce s-a realizat
**Etapa 3a (strategiile):**
- `src/indicators.py`: `macd(close, 12, 26, 9)` → linie, semnal, histogramă (convenția EMA din D12), test de mână.
- `src/strategies/`: S1 Trend Breakout, S2 Momentum Rotation, S3 RSI-2 Pullback, S4 MACD + EMA200, funcții pure
  `prices -> {simbol: semnale}` (SPY doar ca filtru, nu se tranzacționează). Motivul intrării e scris în română,
  cu valorile indicatorilor. `load_strategy("S1")` → `StrategySpec` (`signals`, `params`, `max_hold_bars`,
  `title`); `overrides=` pentru testul ±20%. Interpretările sunt în D14.
- `config/strategies.yaml`: parametrii exact ca în plan, validați strict (pydantic, cheie necunoscută → eroare).
- Teste noi (23): scenarii construite de mână pentru fiecare strategie (intrare, ieșire, stop, țintă, filtrul SPY,
  rotația lunară S2), parametrii din YAML = plan, toate cele 4 trec detectorul de look-ahead și rulează în backtester.

**Etapa 2 (backtesterul):**
1. **Indicatori (`src/indicators.py`, pandas pur):** SMA, EMA, ATR (implicit 20), RSI (2 și 14), Donchian high/low
   (fără bara curentă, shiftat cu 1), ADX (14), randament 12-1 luni. Toți cauzali; convențiile în D12.
2. **Motorul (`src/backtest/engine.py`, `panel.py`):** bar-cu-bar, semnal la închiderea t, execuție la Open t+1;
   costuri pe fiecare parte (slippage 0.10% + jumătate de spread 0.05% + comision fix, toate configurabile în
   `CostModel`); stop/țintă pe High/Low, stop + țintă în aceeași bară → stop; gap peste stop → ieșire la Open;
   ieșire după N zile (`max_hold_bars`); delisting; închidere la final. Fiecare tranzacție: intrare, ieșire, R, MAE,
   MFE, motivul ieșirii, motivul intrării. Respingerile (limite de portofoliu, cantitate prea mică) sunt salvate cu motiv.
3. **Sizing (`src/backtest/sizing.py`):** stub-ul risk guard-ului (risc 0.5%, plafon 1%, expunere max 20%, max 5
   poziții, max 2 pe sector, fără levier). La etapa 4 se înlocuiește cu `src/risk/guard.py` (D9).
4. **Metrici (`metrics.py`):** CAGR, Sharpe, max drawdown, profit factor, expectancy în R, win rate, nr. tranzacții,
   expunere medie; benchmark SPY buy-and-hold cu aceleași metrici, pe aceeași perioadă.
5. **Walk-forward (`walkforward.py`):** ferestre rulante 3 ani calibrare / 1 an test, raportează doar agregatul OOS
   + procentul de ferestre profitabile; cârlig opțional `calibrate` care vede doar datele de antrenare (D10).
6. **Robustețe (`robustness.py`):** Monte Carlo 1.000 (drawdown din reamestecări, randament din bootstrap, D11);
   test cu 500 de intrări aleatoare (aceleași ieșiri și sizing), cu procentul de rulări bătute pe fiecare metrică.
7. **Detector de date din viitor (`lookahead.py`):** rulează strategia pe istoric tăiat și compară semnalele;
   `backtest_strategy` și `walk_forward` îl rulează automat și refuză o strategie care trișează.
8. **Teste noi (55):** indicatori pe valori calculate de mână, costuri pe un exemplu de mână, regula worst-case,
   gap, execuția la Open t+1, limite de portofoliu, strategii care trișează prinse, walk-forward, Monte Carlo,
   testul aleator, invarianta „profitul contului = suma P&L-urilor”. Viteză: o rulare pe 100 de acțiuni × 20 de ani
   ≈ 0,2 s, deci 500 de rulări aleatoare ≈ 1 minut.

## Ce urmează
- **3b — Poarta 1 (Claude Code), pe `etapa-3-strategii`:** date 2006–azi (universul + SPY, o singură descărcare,
  cache); pentru S1–S4: `walk_forward` (3 ani / 1 an), `monte_carlo`, `random_entry_test` (500), testul ±20% pe
  parametri; `reports/gate1.md` cu tabel strategie vs SPY, PASS/FAIL pe cele 7 criterii, nota despre survivorship
  bias, grafice equity vs SPY în `reports/`. NU se optimizează parametrii.

## Blocaje
- Niciun blocaj tehnic.
- **De decis înainte de Poarta 1 (proprietarul):** cu 500 $ și risc 0.5%, riscul pe tranzacție e 2,5 $. Dacă Alpaca
  nu permite ordine bracket (cu stop la broker) pe acțiuni fracționare, botul poate cumpăra doar acțiuni întregi, iar
  multe titluri mari (peste ~100 $) ar fi sărite. Backtesterul suportă ambele variante (`whole_shares`); etapa 5
  verifică regula Alpaca.

## Status teste
- `scripts/check.sh`: **PASS** local (uv sync locked, ruff check, ruff format check, pytest: 106 passed, offline).
