# Planul botului: specificațiile etapelor

Agentul citește regulile comune și DOAR secțiunea etapei lui. Fiecare etapă are sub-pași; un sub-pas = o conversație.

## Reguli comune

- Universul: acțiuni SUA large cap din `config/universe.csv` (simbol, sector), pornind de la S&P 100. SPY = benchmark (doar date).
- Toate strategiile: daily, long-only, semnal pe bara închisă t, execuție la Open t+1.
- Costuri în backtest, pe fiecare parte: slippage 0.10% + jumătate de spread 0.05%, comision 0 (configurabile).
- `BOT_CAPITAL` (din `.env`, implicit 500): capitalul cu care lucrează botul. Equity-ul botului =
  min(equity-ul contului de la broker, BOT_CAPITAL + P&L-ul realizat și nerealizat al botului).
  Sizing-ul, riscul, drawdown-ul și dashboard-ul folosesc DOAR equity-ul botului.
- Fiecare decizie (intrare, ieșire, veto, respingere de la guard) se salvează cu motivul: regula îndeplinită,
  valorile indicatorilor, verdictul AI. Dashboard-ul și Telegram arată „de ce” din aceste câmpuri.
- Starea botului: fișiere în `state/` pe branch-ul `state` (nu pe `main`): `trades.csv`, `equity.csv`, `signals.csv`,
  `vetoes.csv`, `postmortems.csv`, `pending_orders.json`, `status.json` (kill_switch, high_water_mark, equity_ieri, last_run).

### Strategiile (pentru etapa 3)

- **S1 Trend Breakout.** Filtru: SPY > SMA200 și Close > SMA200. Intrare: Close > maximul ultimelor 55 de zile.
  Stop: intrare − 2.5×ATR(20). Ieșire: Close < minimul ultimelor 20 de zile, sau stop.
- **S2 Momentum Rotation.** În prima zi de tranzacționare a lunii: ordonezi universul după randamentul 12-1 luni,
  ții top 5 dintre cele cu Close > SMA200. SPY < SMA200 → fără intrări noi. Ieșire la rebalansare dacă titlul
  iese din top 10. Stop de catastrofă: intrare − 3×ATR(20).
- **S3 RSI-2 Pullback.** Filtru: SPY > SMA200 și Close > SMA200. Intrare: RSI(2) < 10. Ieșire: Close > SMA(5) sau
  după 10 zile. Stop de catastrofă: intrare − 3×ATR(20). Fără R:R minim (se judecă după expectancy).
- **S4 MACD + EMA200 (după TradingLab, adaptată la daily și acțiuni).** Filtru: Close > EMA(200). Intrare: linia
  MACD(12,26,9) taie în sus linia de semnal, cu ambele sub zero. Stop: cel mai jos dintre minimul ultimelor 10 zile
  și Close − 1.5×ATR(20) (deci cel puțin 1.5×ATR distanță). Target: 1.5 × distanța până la stop. Ieșire: stop sau target.
  Fără filtru SPY (varianta originală). Maximum 4 strategii candidate în total: fiecare în plus crește șansa
  ca una să treacă Poarta 1 din noroc.
- **Veto (peste toate):** fără intrări dacă raportarea trimestrială e în următoarele 3 zile de tranzacționare;
  Gemini poate da veto la un șoc negativ sever în știrile din ultimele 48 de ore.

### Poarta 1 (backtest, out-of-sample, după costuri) — o strategie trece doar cu TOATE

1. ≥ 150 de tranzacții OOS (S2: ≥ 100 de poziții-lună).
2. Sharpe ≥ Sharpe SPY + 0.2, SAU (CAGR ≥ CAGR SPY și max DD ≤ 0.7 × max DD SPY).
3. Profit factor ≥ 1.3 și expectancy ≥ +0.1R.
4. Profitabilă în ≥ 60% din ferestrele walk-forward.
5. Cu parametrii la ±20%, PF rămâne > 1.1.
6. Bate 95% din 500 de rulări cu intrări aleatoare (aceleași ieșiri și sizing).
7. Monte Carlo (1.000 reamestecări): drawdown-ul la percentila 95 < 20%.

### Poarta 2 (paper → bani reali) — toate

1. ≥ 12 săptămâni de paper continuu; nicio rulare ratată nerezolvată în ultimele 30 de zile.
2. 100% din poziții cu stop la broker; zero ordine duplicate; reconciliere 100% corectă.
3. Slippage mediu față de model ≤ 0.10%.
4. Rezultatul paper în banda 5–95% din Monte Carlo-ul backtestului, pentru același număr de tranzacții.
5. Kill switch testat pe toate cele trei căi (dashboard, Telegram, workflow), fiecare sub 2 minute.
6. Contul live pregătit, cheie fără drept de retragere, exportul fiscal funcțional.

---

## Etapa 0 — Fundația · Antigravity

Fișierele de reguli (`AGENTS.md`, `CLAUDE.md`, `GEMINI.md`, `PROGRESS.md`, `docs/`, `.claude/`, `.agents/`,
`scripts/set_keys.sh`, `.gitignore`, `.env.example`) sunt deja scrise. Rămâne:

- [x] **0a.** `git init` pe `main`; `pyproject.toml` cu uv (Python 3.12): pandas, numpy, yfinance, alpaca-py, requests,
  pydantic, python-dotenv, google-genai; dev: pytest, pytest-socket, ruff. Fără ML greu, fără TA-Lib.
  `scripts/check_fast.sh` (ruff + pytest) și `scripts/check.sh` (uv sync --locked, ruff check, ruff format --check, pytest).
  Un test trivial. `.github/workflows/ci.yml` care rulează `scripts/check.sh` la push și PR (nu pe branch-ul `state`).
- [x] **0b.** Verifici că `.env` nu e urmărit de git. `gh repo create theo-trading-bot --private --source . --push`.
  CI verde pe GitHub. Îi spui proprietarului să ruleze `bash scripts/set_keys.sh` (cel puțin cheile Alpaca).

## Etapa 1 — Date de piață · Antigravity

- [x] **1a.** `src/config.py` (Pydantic, citește `.env`). `config/universe.csv` cu S&P 100 + sector. `src/data/`:
  `load_daily(symbols, start)` cu yfinance (`auto_adjust=True`) pentru 20 de ani; `load_recent(symbols)` cu Alpaca
  Market Data (feed IEX). Cache local în `data/cache/` (ignorat de git).
- [x] **1b.** `drop_incomplete_bar()` (elimină bara zilei curente dacă piața din New York nu s-a închis) și `validate()`
  (fără NaN, prețuri ≤ 0, zile duplicate, goluri anormale; raportează, nu ascunde). Teste pe fixtures.

## Etapa 2 — Backtester · Claude Code

- [x] **2a.** `src/indicators.py`: SMA, EMA, ATR(20), RSI(2), RSI(14), Donchian high/low (shiftat cu 1 bară), ADX(14),
  randament 12-1 luni. Teste cu valori calculate de mână.
- [x] **2b.** `src/backtest/engine.py`, bar-cu-bar: semnal la t, execuție la Open t+1 cu costurile din regulile comune;
  stop și ieșiri pe High/Low; dacă în aceeași bară sunt atinse și stop-ul și ținta → stop (worst case); gap peste
  stop → ieșire la Open. Sizing prin aceeași funcție ca risk guard-ul (stub până la etapa 4: risc 0.5%, expunere max
  20%, max 5 poziții, max 2 pe sector). Pe tranzacție: intrare, ieșire, R, MAE, MFE, motivul ieșirii.
- [x] **2c.** Metrici (CAGR, Sharpe, max DD, PF, expectancy în R, win rate, nr. tranzacții, expunere), benchmark SPY
  buy-and-hold, walk-forward pe ferestre rulante (3 ani calibrare / 1 an test, raportezi doar agregatul OOS),
  Monte Carlo (1.000), test cu intrări aleatoare (500). Teste obligatorii: o strategie care „trișează” cu date din
  viitor e prinsă de un test; regula worst-case; costurile pe un exemplu calculat de mână.

## Etapa 3 — Strategii și Poarta 1 · Claude Code

- [x] **3a.** `src/strategies/`: S1, S2, S3, S4 exact ca în regulile comune, funcții pure (date → semnale), parametrii în
  `config/strategies.yaml`. Teste pe scenarii construite de mână. S4 are nevoie de indicatorul MACD(12,26,9)
  (linie, semnal, histogramă), care nu există încă: îl adaugi în `src/indicators.py`, cu test pe valori calculate
  de mână, folosind aceeași convenție EMA ca restul (D12).
- **3b.** Rulezi walk-forward + Monte Carlo + testul aleatoriu pe 2006–azi pentru fiecare strategie. `reports/gate1.md`:
  tabel strategie vs SPY, PASS/FAIL pe fiecare din cele 7 criterii, testul ±20%, nota despre survivorship bias,
  grafice equity vs SPY în `reports/`. NU optimiza parametrii ca să treacă. Raport de 5 rânduri pentru proprietar.
  Dacă nicio strategie nu trece: te oprești și scrii asta clar.

## Etapa 4 — Risk guard · Claude Code

`src/risk/guard.py`, constante `typing.Final`: MAX_RISK_PER_TRADE=0.01, MAX_POSITION_NOTIONAL=0.20,
MAX_OPEN_POSITIONS=5, MAX_PER_SECTOR=2, MAX_DAILY_LOSS=0.025, MAX_DRAWDOWN=0.10. Equity = equity-ul botului (BOT_CAPITAL).
- `size_position(entry, stop, equity, config_risk)`: risc efectiv = min(config_risk, MAX_RISK_PER_TRADE);
  cantitate = min(risc/(entry−stop), equity×MAX_POSITION_NOTIONAL/entry).
- `check_entry(signal, state)` respinge cu motiv scris: kill activ; zi blocată după −2.5%; drawdown ≥ 10% (declanșează
  și KILL); 5 poziții; 2 pe sector; simbol deja deținut; lipsă stop sau stop ≥ entry.
- `validate_stop_change(old, new)`: doar strângere. Configul poate doar să scadă valorile.
- Teste pentru fiecare regulă + un test care verifică valorile exacte ale constantelor (dacă se schimbă, CI pică).
  Backtesterul (etapa 2) trece pe funcția reală de sizing.

## Etapa 5 — Broker Alpaca (paper) · Claude Code

`src/broker/`: interfață `BrokerAdapter` + `AlpacaAdapter` (alpaca-py). Paper implicit; LIVE doar cu
`TRADING_MODE=LIVE` + `LIVE_APPROVED.md` + `reports/gate2.md` = PASS.
- Doi pași: jobul de după închidere scrie semnalele aprobate în `state/pending_orders.json`; jobul de după deschidere
  (≥ 15 minute după open, verificat cu clock-ul Alpaca) le execută.
- Fiecare intrare = ordin bracket/OTO cu stop la broker. `client_order_id` determinist (strategie-simbol-dată);
  înainte de orice ordin verifici ordinele și pozițiile existente (un job rulat de două ori nu dublează nimic).
- Verifici în documentația Alpaca dacă bracket e permis pe fracționare; dacă nu: acțiuni întregi; sub 1 acțiune →
  sari peste tranzacție și loghezi motivul. NICIODATĂ o poziție fără stop.
- Ieșirile strategiilor se decid după închidere și se execută după deschidere. `reconcile()`: la orice nepotrivire →
  alertă + fără intrări noi. `liquidate_all()` pentru kill. Teste cu API simulat.

## Etapa 6 — Stare, veto, post-mortem · Antigravity

- **6a.** Stocarea în `state/` pe branch-ul `state` (fișierele din regulile comune), cu scriere sigură (o rulare = un commit).
- **6b.** Blackout la earnings (calendarul Finnhub, fallback yfinance). `src/ai/veto.py` cu google-genai, model din
  `GEMINI_MODEL` (implicit cel mai ieftin Flash-Lite disponibil; verifici la pornire ce modele are cheia). Input: simbol,
  strategie, titlurile din ultimele 48 h (Finnhub company-news). Output JSON validat: `{veto, severity 0-3, reason_ro}`;
  veto doar la severity 3. Cache după hash-ul titlului; rate limiter conservator; API picat → fără veto, dar loghezi.
  Semnalele blocate sunt urmărite în umbră. Cheia Finnhub e comună cu alt proiect: reîncercare la HTTP 429.
- **6c.** `src/ai/autopsy.py`: la fiecare tranzacție închisă calculezi R, MAE, MFE, slippage față de model; Gemini
  clasifică (NORMAL_LOSS, REGIME_CHOP, NEWS_SHOCK, LATE_ENTRY, GAVE_BACK_PROFIT, BAD_FILL) + lecție de 2 propoziții în
  română. AI-ul nu schimbă reguli. Teste cu Gemini simulat.

## Etapa 7 — Rulare zilnică, alerte, kill · Antigravity (apoi „review etapa 7” cu Claude Code)

Workflow-uri cu concurrency group `trading`:
- `signals.yml`: luni–vineri 21:30 UTC. Întâi testele (dacă pică: nu tranzacționează, alertă). Apoi date → semnale →
  veto → guard → `pending_orders.json` → equity și jurnal → commit pe `state`.
- `execute.yml`: luni–vineri 14:50 și 15:50 UTC (acoperă ora de vară/iarnă); execută doar dacă piața e deschisă de
  ≥ 15 minute și ordinele zilei nu au fost trimise.
- `kill.yml` (workflow_dispatch): `liquidate_all()` + kill_switch=true + alertă. `watchdog.yml`: zilnic; nicio rulare
  reușită în 26 h → alertă.
- Secretele în GitHub Secrets, urcate din `.env` cu `gh secret set` (fără să le afișezi).
- `src/alerts/telegram.py`, în română: intrare (simbol, strategie, cantitate, stop, risc %, de ce), ieșire (P&L, R,
  lecția), rezumat zilnic, −2.5% pe zi, KILL, orice workflow eșuat. Chat ID-ul îl afli din `getUpdates`.

## Etapa 8 — Dashboard simplu · Antigravity

O singură pagină, în română, bună pe telefon și pe laptop. Next.js (App Router, TypeScript, Tailwind, Recharts) în
`dashboard/`, proiect Vercel **nou** `theo-trading-bot` (nu atinge alte proiecte din cont).
- Citește `state/` de pe branch-ul `state` prin GitHub API, server-side, cu `GH_DISPATCH_TOKEN`. Login cu
  `DASHBOARD_PASSWORD` (cookie httpOnly).
- 4 blocuri: (1) bara de sus: PAPER/LIVE, capital, profit total (€ și %), profit azi, drawdown, buton KILL roșu cu
  confirmare (POST `/api/kill` → workflow_dispatch pe `kill.yml`); (2) graficul capitalului vs S&P 500 (aceeași sumă
  pusă în SPY la start); (3) poziții deschise: simbol, de când, profit acum, stop; (4) jurnalul: un card pe tranzacție,
  cel mai nou sus — „Am cumpărat NVDA” + de ce în 1–2 fraze, verdictul Gemini, rezultatul, lecția.
- `/api/telegram`: webhook cu `/kill` și `/status` (verifică secret_token și chat_id).
- Până există date reale: date de exemplu din `tests/fixtures/state/`. `npm run build` fără erori, deploy, linkul
  către proprietar. Variabilele în Vercel cu `vercel env add`, din `.env`.

## Etapa 9 — Review, Poarta 2, fiscal · Antigravity

- `scripts/weekly_review.py` → `reports/weekly/AAAA-SS.md`: equity, drawdown, tranzacții, slippage față de model,
  veto-uri vs umbră, categoriile de post-mortem, poziția în banda Monte Carlo.
- `scripts/gate2_check.py` → `reports/gate2.md` cu PASS/FAIL pe cele 6 criterii ale Porții 2.
- `scripts/preflight.py`: secrete prezente, conexiune Alpaca, model Gemini disponibil, Telegram, testul constantelor din guard.
- `docs/CHAOS.md`: testul kill pe 3 căi, job rulat de două ori, rulare ratată.
- `scripts/tax_export.py`: câștig/pierdere realizată pe an, în RON la cursul BNR din ziua tranzacției, CSV pentru D212
  (broker străin: 16% pe câștigul net anual). Notă: metoda se confirmă cu un contabil.

## Etapa 10 — Bani reali · Claude Code (doar după Poarta 2)

Rulezi DOAR dacă există `LIVE_APPROVED.md` scris de proprietar și `reports/gate2.md` = PASS.
- A (Alpaca live): același adaptor, `ALPACA_PAPER=false`, chei live în GitHub Secrets; risc 0.5%; capitalul crește pe
  trepte (luna 4: 33%, luna 5: 66%, luna 6: 100%, risc max 1%). Paper rulează în paralel pentru comparație.
- B (Trading 212 Invest), doar dacă Alpaca nu acceptă România: pe live API-ul acceptă doar ordine Market, deci stopurile
  le ține botul (`guard.yml` la 15 minute în orele de piață); endpoint-ul de ordine nu e idempotent (verifici pozițiile
  înainte); cont în RON → costul FX în model; refaci Poarta 1 cu aceste costuri.
Nu activezi nimic live fără să-i arăți proprietarului diff-ul și să confirme.
