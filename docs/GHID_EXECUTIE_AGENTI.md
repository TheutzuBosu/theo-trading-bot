# Ghid de execuție „Mură în Gură” pentru Agenți AI (Gemini Flash, Codex / GPT Go, Antigravity, Claude Code)

Acest document conține instrucțiunile exacte, pas cu pas, cu nume de fișiere, semnături de funcții, formule matematice
și comenzi de verificare, astfel încât **orice model AI** (inclusiv modele rapide precum Gemini Flash sau GPT Go / Codex)
să execute fără greșeală și fără să inventeze reguli.

---

## 1. Reguli de aur (Cum să NU dai rateu niciodată)

1. **Nu ghici și nu inventa nume de funcții.** Înainte să scrii cod, importă exact funcțiile existente din tabelul de la
   Secțiunea 2.
2. **Fără date din viitor (Look-Ahead Bias = INTERZIS):**
   - La minutul `t`, ai voie să folosești doar barele închise `<= t` și zilele anterioare `< d`.
   - Orice intrare semnalată la închiderea barei `t` se execută automat în motor la **Open-ul barei `t + 1`**.
   - Orice strategie nouă TREBUIE testată cu `assert_no_lookahead` din `src/backtest/lookahead.py`.
3. **Nu folosi internetul în testele `pytest`.** `pytest` rulează cu `--disable-socket`. Orice test folosește date din
   `tests/fixtures/` sau obiecte simulate (`FakeSession`, `FakeClient`).
4. **Verifică după fiecare fișier scris:**
   - Rulează `uv run pytest tests/test_<fisier>.py -q`
   - Rulează `uv run ruff check --fix . && uv run ruff format .` (limita de linie este de **100 de caractere**!).
5. **Nu atinge secretele:** nu afișa niciodată conținutul `.env` în terminal sau în chat.
6. **Folosește sub-agenți ieftini (`haiku` / `flash_lite`) pentru munca de rutină:**
   - Dacă ești pe un model mare (Claude Opus sau Gemini High/Pro) și trebuie să extragi reguli dintr-un PDF/site, să
     cauți prin loguri sau să verifici fișiere lungi, **nu consuma tokenii modelului mare**: lansează un sub-agent cu
     modelul mic (`haiku` în Claude Code, sau `Model="flash_lite"` / `Model="flash"` în Antigravity) și cere-i să îți
     returneze doar formulele sau răspunsul scurt. Modelul mare se concentrează exclusiv pe arhitectură și matematică.

---

## 2. Ce există deja în proiect (Importuri exacte gata de folosit)

| Ce vrei să faci | De unde imporți | Funcții / Clase exacte |
|---|---|---|
| Setări și chei `.env` | `from src.config import settings` | `settings.ALPACA_API_KEY`, `settings.BOT_CAPITAL` (500.0), `settings.TELEGRAM_BOT_TOKEN`, `settings.TELEGRAM_CHAT_ID` |
| Date 1 minut (2016–2026) | `from src.data.intraday import load_minute_bars, nyse_sessions` | `df = load_minute_bars("SPY", "sip", start="2016-01-04", end="2026-11-02")` |
| Costuri tranzacționare | `from src.backtest.intraday_costs import cost_per_side, round_trip_cost, trade_allowed` | `cost_per_side("SPY", "stock")` → `0.015 $`, `cost_per_side("SPY", "cfd")` → `0.08 $` |
| Simulator intraday | `from src.backtest.intraday_engine import IntradayPanel, IntradaySignals, IntradayConfig, run_intraday, SIGNAL_COLUMNS, TRADE_COLUMNS` | `res = run_intraday(panel, signals, config)` |
| Veto ședințe Fed (FOMC) | `from src.backtest.fomc import is_fomc_blackout, fomc_blackout_mask` | Blochează intrările la ±30 min de anunțul FOMC |
| Metrici + Test aleator | `from src.backtest.intraday_metrics import summarize_intraday, r_stats, deflated_sharpe, random_direction_test` | Calculează Expectancy în R, t-stat cu Bonferroni N=9, DSR, p-value direcție aleatoare |
| Detector Look-Ahead | `from src.backtest.lookahead import assert_no_lookahead` | `assert_no_lookahead(df, fn, columns=SIGNAL_COLUMNS)` |
| Alerte Telegram (RO) | `from src.alerts.telegram import send_entry_alert, send_exit_alert, send_daily_summary_alert, send_daily_loss_limit_alert, send_kill_alert, send_error_alert` | Trimite mesaje în română pe `@thetheotrading_bot` |

### Coloanele obligatorii pentru orice strategie intraday (`SIGNAL_COLUMNS`)
Orice funcție de strategie intraday primește `df: pd.DataFrame` (bare de 1 minut cu index `America/New_York` și coloanele
`open, high, low, close, volume, trade_count, vwap`) și returnează un `pd.DataFrame` cu același index și coloanele:
- `direction`: `1` (long), `-1` (short), sau `0` (fără semnal de intrare pe această bară)
- `stop`: `float` (prețul de stop-loss inițial pentru o intrare nouă, sau noul prag de trailing stop pentru o poziție deschisă; `np.nan` dacă nu se aplică)
- `target`: `float` (prețul țintă de profit, sau `np.nan` dacă strategia nu are țintă fixă)
- `target_fraction`: `float` (fracțiunea din poziție închisă la `target`, de ex. `0.5` pentru D1b sau `1.0` implicit)
- `size`: `float` (fracțiunea din capital alocată poziției, calculată din ținta de volatilitate, ex. `0.95`)
- `exit`: `bool` (`True` dacă strategia cere ieșirea la Open-ul barei următoare, `False` altfel)
- `entry_reason`: `str` (explicația în română a semnalului, ex. `"D1: SPY (585,00 $) > banda superioară (584,10 $) la 10:00 ET"`)

---

## 3. Ordinea de folosire a modelelor (Faza B)

Proprietarul folosește modelele în această ordine, după limita disponibilă, iar **niciun agent nu se blochează la `/preia`**:
1. **Claude Code (Opus 5.5 + sub-agenți Haiku):** rulează acum pe **B3** (strategiile D1, D1b, D2 + Poarta 1 B).
2. **Antigravity pe Gemini 4 Argon (High) + sub-agenți `flash_lite`:** preia imediat după Claude Code (B4, B5, B6c), cât timp are usage.
3. **Antigravity pe Gemini 3.8 Flash (High) sau Codex pe GPT Go (Luna 6 High):** continuă orice pas rămas (B4, B5, B6c, B7), urmând mecanic rețetele „mură în gură” din secțiunile 4, 5 și 6 de mai jos.

---

## 4. Rețeta pas cu pas pentru Etapa B4: Filtru ML Meta-Labeling + Învățare Zilnică din Greșeli

> **Când se execută:** OBLIGATORIU imediat după B3 (indiferent dacă B3 trece sau nu Poarta 1 B — proprietarul a decis că
> botul merge până la capăt pe Alpaca Paper ca să tranzacționeze live pe contul demo și să învețe zilnic din greșeli!).
> **Branch:** `faza-b4-ml-filter` (creat din `main` actualizat).

### Ce face mai exact acest pas (explicat simplu)
Strategia matematică (D1) decide **când** și **în ce direcție** vrea să intre. Modelul de Machine Learning (ML) NU
inventează intrări noi, ci învață din istoric **când semnalul D1 are șanse mari să fie o capcană** și îi pune o notă
(probabilitate de câștig între `0.0` și `1.0`). Dacă probabilitatea e sub `0.55`, tranzacția este sărită.

### Pasul B4.1 — Adăugare `scikit-learn`
Rulează în terminal:
```bash
uv add scikit-learn
```

### Pasul B4.2 — Scrie fișierul `src/ai/meta_label.py`
Creează `src/ai/__init__.py` și `src/ai/meta_label.py` cu următoarele funcții exacte:

1. **`FEATURE_COLUMNS` (exact aceste 10 caracteristici calculate DOAR din date `<= t`, fără look-ahead):**
   - `minute_of_day`: minute scurse de la `09:30` ET (ex. `10:00` → `30.0`).
   - `dist_from_band_bps`: `(close_t / band_t - 1.0) * 1e4` (cât de puternică e spargerea benzii, în puncte de bază).
   - `dist_from_vwap_bps`: `(close_t / vwap_session_t - 1.0) * 1e4` (distanța față de VWAP-ul sesiunii).
   - `rv_30m`: deviația standard a randamentelor de 1 minut din ultimele 30 de minute închise.
   - `sigma_14d`: volatilitatea zilnică a simbolului pe ultimele 14 zile închise (înainte de ziua curentă).
   - `overnight_gap_bps`: `(open_zi_curenta / close_zi_anterioara - 1.0) * 1e4`.
   - `ret_since_open_bps`: `(close_t / open_zi_curenta - 1.0) * 1e4`.
   - `vol_ratio_14d`: volumul cumulat de la `09:30` până la minutul `t` împărțit la media pe ultimele 14 zile a volumului cumulat până la același minut `t`.
   - `day_of_week`: ziua săptămânii (`0` = Luni ... `4` = Vineri).
   - `cost_to_risk`: `round_trip_cost / initial_risk_per_share`.

2. **`build_meta_dataset(bars: pd.DataFrame, trades: pd.DataFrame) -> tuple[pd.DataFrame, pd.Series]`**:
   - Pentru fiecare tranzacție din `trades` (rezultatul rulării D1 în backtester, care are deja eticheta Triple Barrier
     prin stop, țintă sau închiderea de la `15:59` ET, net de costuri):
   - Extrage valorile celor 10 caracteristici din `bars` la momentul `signal_time` (bara închisă care a generat semnalul).
   - Construiește ținta binară `y = (trades["r_multiple"] > 0.0).astype(int)` (`1` = tranzacție câștigătoare net de costuri, `0` = pierzătoare).
   - Returnează `(X, y)` indexate după `signal_time`.

3. **`purged_walk_forward_probs(X: pd.DataFrame, y: pd.Series, exit_times: pd.Series, train_months: int = 24, embargo_days: int = 5) -> pd.Series`**:
   - Pentru fiecare lună de test `M` (după primele `train_months` luni):
     - Mulțimea de antrenare conține doar rândurile din fereastra de `train_months` luni anterioare lunii `M` a căror
       `exit_time` este cu cel puțin `embargo_days` zile înainte de prima zi a lunii `M` (**Purging + Embargo**, ca să
       nu existe nicio scurgere de informație între antrenare și test).
     - Antrenează un pipeline `StandardScaler() + LogisticRegression(C=0.5, max_iter=500, random_state=42)` pe `(X_train, y_train)`.
     - Prezice probabilitatea `predict_proba(X_test)[:, 1]` pentru semnalele din luna `M`.
   - Returnează o serie `probs` cu probabilitățile out-of-sample (OOS) pentru toate lunile testate.

4. **`apply_meta_filter(signals: pd.DataFrame, probs: pd.Series, threshold: float = 0.55) -> pd.DataFrame`**:
   - Copiază `signals`; acolo unde `probs < threshold` (sau unde `probs` este `NaN`), setează `direction = 0`.
   - Adaugă în `entry_reason` sufixul `f" [ML p={prob:.2f}]"`.

### Pasul B4.3 — Re-antrenare zilnică din greșeli (`src/ai/daily_learner.py`) și Teste
1. În `src/ai/daily_learner.py`, scrie funcția `retrain_on_daily_trades(history_X: pd.DataFrame, history_y: pd.Series, new_X: pd.DataFrame, new_y: pd.Series, model_path: Path) -> dict`:
   - Adaugă tranzacțiile închise azi (`new_X`, `new_y`) la istoricul de antrenament, cu o pondere mai mare (`sample_weight = 3.0` pentru ultimele 20 de zile de tranzacționare, `1.0` pentru istoricul vechi), astfel încât **botul învață direct din greșelile recente** și scade automat probabilitatea tiparelor care au pierdut bani.
   - Salvează statisticile zilei (`trained_samples`, `recent_win_rate`, `top_mistake_feature`, `updated_threshold`) în `state/learning_stats.json` pentru a fi afișate în Dashboard.
2. Scrie `tests/test_meta_label.py` care verifică offline pe date sintetice:
   - Că `build_meta_dataset` nu citește nicio bară după `signal_time` (test de look-ahead).
   - Că `purged_walk_forward_probs` respectă embargoul și nu folosește niciodată tranzacții din luna de test la antrenare.
   - Că `retrain_on_daily_trades` scade probabilitatea unui tipar după ce acel tipar înregistrează pierderi repetate.
3. După ce toate testele trec:
   - Rulează `bash scripts/check.sh`.
   - Fă commit, push, PR și unește în `main`.
   - Rulează `cd dashboard && vercel --prod --yes` ca dashboard-ul să fie la zi.

---

## 5. Rețeta pas cu pas pentru Etapa B5: Risk Guard Intraday + Adaptor Broker Alpaca Paper

> **Când se execută:** OBLIGATORIU imediat după B4. Pe Alpaca Paper **NU există limită de număr de tranzacții pe zi**
> (botul poate lua oricâte semnale valide apar în sesiune; singura regulă de poziție e max 1 poziție deschisă simultan pe
> același simbol).
> **Branch:** `faza-b5-risc-broker` (creat din `main` actualizat).

### Pasul B5.1 — `src/risk/guard.py` + `tests/test_risk_guard.py`
Creează `src/risk/__init__.py` și `src/risk/guard.py`.
1. **Constante hard-codate în `src/risk/guard.py` (NU se citesc din `.env`, sunt bătute în cuie conform `docs/PLAN_DAYTRADING.md` și D24):**
   - `MAX_RISK_PER_TRADE_PCT = 0.005` (`0.5%` din capital pe o tranzacție)
   - `MAX_DAILY_LOSS_PCT = -0.02` (`-2.0%` pierdere zilnică → oprește intrările noi în acea zi)
   - `MAX_DRAWDOWN_KILL_PCT = -0.15` (`-15.0%` față de vârful istoric al contului → declanșează `KILL` și blochează botul)
   - `MAX_POSITIONS_PER_SYMBOL = 1` (cel mult 1 poziție deschisă pe `SPY` și 1 pe `QQQ`)
   - `MAX_TOTAL_EXPOSURE = 1.0` (`1.0x` equity pe contul de 500 $ fără marjă / long-only, D24)
   - `NO_ENTRY_LAST_MINUTES = 15` (fără intrări noi după `15:45` ET la sesiune normală sau `12:45` ET la închidere timpurie)
   - `MAX_SPREAD_MULTIPLIER = 2.0` (fără intrare dacă `current_spread > 2.0 * typical_spread`)
   - `ALLOWED_SYMBOLS = frozenset({"SPY", "QQQ"})`
2. **Funcția pură `evaluate_order_risk(...) -> tuple[bool, str]`:**
   - Verifică în ordine:
     a. `kill_switch_active` → `(False, "KILL switch activ")`
     b. `drawdown_pct <= MAX_DRAWDOWN_KILL_PCT` → `(False, "Drawdown maxim atins (-15%): KILL")`
     c. `daily_pnl_pct <= MAX_DAILY_LOSS_PCT` → `(False, "Limita zilnică de pierdere (-2%) a fost atinsă")`
     d. `symbol not in ALLOWED_SYMBOLS` → `(False, f"Simbol nepermis: {symbol}")`
     e. `direction != "long"` (când `long_only=True`, D24) → `(False, "Contul de 500 $ permite doar poziții LONG")`
     f. `stop is None or stop <= 0 or stop >= entry_price` → `(False, "Ordin fără stop-loss valid sub prețul de intrare")`
     g. `is_fomc_blackout(timestamp)` (din `src/backtest/fomc.py`) → `(False, "Veto FOMC: ±30 min de anunțul Fed")`
     h. `minutes_to_close <= NO_ENTRY_LAST_MINUTES` → `(False, "Ultimele 15 minute ale sesiunii: fără intrări noi")`
     i. `current_spread > MAX_SPREAD_MULTIPLIER * typical_spread` → `(False, "Spread curent > 2x spread-ul tipic")`
     j. `symbol in open_positions` → `(False, f"Există deja o poziție deschisă pe {symbol}")`
     k. `(current_exposure + order_notional) / equity > MAX_TOTAL_EXPOSURE` → `(False, "Expunerea depășește plafonul 1x equity")`
     l. `risk_dollars / equity > MAX_RISK_PER_TRADE_PCT + 1e-6` → `(False, "Riscul pe tranzacție depășește 0,5% din capital")`
     m. `not trade_allowed(entry_price - stop, round_trip_cost(symbol, "stock"))` → `(False, "Risc inițial < 2x costul dus-întors")`
   - Dacă trece toate cele 13 verificări: `(True, "OK")`.
3. **Funcția `can_move_stop(current_stop: float, new_stop: float, direction: str = "long") -> bool`:**
   - Pentru `long`: returnează `new_stop > current_stop` (stop-ul poate doar să urce / să se strângă, NICIODATĂ să coboare!).
4. Scrie `tests/test_risk_guard.py` cu câte un test unitar offline pentru fiecare dintre cele 13 reguli + `can_move_stop`.

### Pasul B5.2 — `src/broker/alpaca_paper.py` + `tests/test_broker.py`
Creează `src/broker/__init__.py` și `src/broker/alpaca_paper.py`.
1. **Verificare de siguranță la inițializare:**
   - Dacă `settings.TRADING_MODE == "LIVE"`, verifică existența fișierului `LIVE_APPROVED.md` în rădăcină și că `reports/gate2.md` conține `PASS`. Altfel ridică `RuntimeError("TRADING_MODE=LIVE este interzis fără LIVE_APPROVED.md și Poarta 2 = PASS")`.
2. **Idempotență prin `make_client_order_id(symbol: str, timestamp_str: str, direction: str) -> str`:**
   - Generează un ID determinist (ex. `f"theo-{symbol}-{direction}-{timestamp_str}"`), astfel încât dacă procesul se repornește în același minut, Alpaca refuză dublura și nu plasează două ordine.
3. **Metode în clasa `AlpacaPaperAdapter(trading_client)`:**
   - `get_account_state() -> dict`: returnează `equity`, `cash`, `buying_power`.
   - `get_open_positions() -> dict[str, dict]`: pozițiile deschise la broker, indexate după simbol.
   - `reconcile(local_symbols: set[str]) -> dict`: compară pozițiile din `state/` cu cele de la Alpaca și raportează orice diferență (`missing_at_broker`, `unexpected_at_broker`).
   - `submit_long_with_stop(symbol: str, qty: float, stop_price: float, client_order_id: str) -> dict`: verifică că `stop_price > 0`, apoi trimite ordinul cu `client_order_id`.
   - `liquidate_all() -> int`: anulează toate ordinele deschise (`cancel_orders`) și închide toate pozițiile (`close_all_positions`).
4. Scrie `tests/test_broker.py` cu `FakeTradingClient` (fără internet) care testează: blocarea `LIVE` fără `LIVE_APPROVED.md`, idempotența `client_order_id`, refuzul ordinului fără stop, reconcilierea și `liquidate_all()`.

---

## 6. Rețeta pas cu pas pentru Etapa B6c: Veto AI pe știri, Post-Mortem și Rulare Live pe Demo

> **Când se execută:** După ce B5 (Risk Guard + Broker Alpaca Paper, făcut de Claude Code) este unit în `main`.
> **Agent:** Orice agent (Gemini Flash / Codex / Antigravity).
> **Branch:** `faza-b6c-live-demo` (creat din `main` actualizat).

### Pasul B6c.1 — Veto pe știri (`src/ai/veto.py` + `tests/test_veto.py`)
1. Funcția `fetch_recent_news(symbol: str, finnhub_key: str, session=None) -> list[dict]`:
   - Apelează `https://finnhub.io/api/v1/company-news` (sau știri generale piață pentru SPY/QQQ din ultimele 4 ore).
   - Dacă cheia lipsește sau API-ul dă eroare, returnează `[]` (fără să crape).
2. Funcția `check_news_veto(symbol: str, direction: str, headlines: list[str], client=None) -> tuple[bool, str]`:
   - Dacă `headlines` e goală, returnează `(True, "Fără știri majore recente.")` (`True` = permis).
   - Trimite titlurile către modelul `settings.GEMINI_MODEL` (`gemini-2.5-flash-lite`) cu promptul strict:
     *„Ești un filtru de risc. Avem un semnal {direction} pe {symbol}. Răspunde în JSON `{"allow": true/false, "reason": "1 frază în română"}`. Blochează (`allow: false`) DOAR dacă există o știre de criză extremă sau șoc macroeconomic neașteptat în ultimele ore. Nu genera semnale noi.”*
   - Returnează `(allow, reason)`.
3. Testează totul offline în `tests/test_veto.py` cu răspunsuri HTTP/Gemini simulate.

### Pasul B6c.2 — Post-Mortem în română (`src/ai/autopsy.py` + `tests/test_autopsy.py`)
1. Funcția `generate_trade_lesson(trade: dict, client=None) -> str`:
   - Primește dicționarul unei tranzacții închise (`symbol`, `direction`, `pnl`, `r_multiple`, `entry_reason`, `exit_reason`, `mae_r`, `mfe_r`).
   - Dacă `client` (Gemini) nu e disponibil, returnează o explicație deterministă în română (ex. dacă `exit_reason == "stop"`, *„Prețul s-a întors sub pragul de protecție; pierderea a fost limitată la 1 R conform regulii.”*).
   - Dacă Gemini răspunde, returnează 1 frază simplă în română pentru jurnalul din dashboard.

### Pasul B6c.3 — Procesul Live pe Alpaca Paper (`src/live/runner.py`) și Scrierea stării (`src/live/state_writer.py`)
1. Funcția `write_state_files(state_dir: Path, summary: dict, equity_df: pd.DataFrame, trades_df: pd.DataFrame) -> None`:
   - Scrie `state/summary.json`, `state/equity.csv` și `state/trades.csv` (cu exact coloanele `TRADE_COLUMNS` din `src/backtest/intraday_engine.py`, plus lecția în `entry_reason` / `lesson`), și le urcă pe branch-ul `state` pe GitHub, astfel încât **proprietarul vede în timp real în Dashboard (`https://theo-trading-bot.vercel.app`) tot ce tranzacționează botul pe Alpaca Paper și ce a învățat din greșeli**.
2. În `src/live/runner.py`:
   - Rulează bucla sesiunii SUA pe Alpaca Paper (`SPY` și `QQQ`), fără limită de număr de tranzacții pe zi: de fiecare dată când apare un semnal și nu există deja o poziție deschisă pe acel simbol, verifică `meta_label.py`, `veto.py` și `guard.py`, trimite ordinul la Alpaca Paper, trimite alerta pe Telegram și actualizează `state/`.
   - La finalul fiecărei zile (după închiderea pozițiilor la 15:59 ET), rulează automat `autopsy.py` (analiza greșelilor zilei) și `daily_learner.py` (re-antrenarea modelului pe tranzacțiile de azi) și trimite rezumatul zilnic pe Telegram + în Dashboard.

### Pasul B6c.4 — Verificare finală și Deploy în Git + Vercel
- Rulează `bash scripts/check.sh`.
- Actualizează `PROGRESS.md`, fă commit, push, PR și unește în `main`.
- Fă deploy în Vercel: `cd dashboard && vercel --prod --yes` (ca toate modificările din dashboard să fie live).
