# Theo Trading Bot: instrucțiuni pentru agenți AI

Fișierul acesta e sursa unică de reguli pentru orice agent (Claude Code, Antigravity, Codex, Gemini).
Citește-l integral înainte de orice acțiune.

## Scop

Un bot de trading automat, **personal**: tranzacționează doar contul propriu al proprietarului, cu banii lui.
Nu se dă, nu se vinde și nu se conectează la conturile altor persoane (asta ar cere autorizare ASF).
Proiectul e complet separat de Market Lens: alt folder, alt repo, alte chei (excepție: cheia Finnhub, D6).

- **Faza B (activă, D20–D31): Day trading intraday pe `SPY` și `QQQ` (bare de 1 minut)** pe **Alpaca Paper cu 500 $** (suma reală pe care proprietarul o va depune după perioada de probă de 3 luni).
- **Ambele direcții (`Long + Short`) și levierul sunt permise și active (D31):**
  - Semnalele se calculează pe `SPY` și `QQQ` (`D1b` principal + `D1` referință) și sunt filtrate de analiza AI + statistică (`meta_label.py`, `daily_learner.py`, `news_veto.py`).
  - Pe contul de **500 $** (unde Alpaca blochează short-ul direct pe fracțiuni sub 2.000 $), semnalele **Short (`-1`)** se execută automat cumpărând ETF-uri inverse lichide (`SH` `-1×` sau `SDS` `-2×` pentru `SPY`; `PSQ` `-1×` sau `QID` `-2×` pentru `QQQ`), iar semnalele **Long (`+1`)** cumpără `SPY`/`QQQ` (sau `SSO`/`QLD` `2×` când levierul este activat). Dacă balanța contului e `>= 2.000 $`, adaptorul poate folosi și short/marjă directă.
- **Fără limită la numărul de trade-uri pe zi:** botul poate face oricâte trade-uri pe zi, atâta timp cât este momentul potrivit și semnalul trece de analiza strategiei, de filtrul de învățare (`daily_learner` + `meta_label`) și de `risk/intraday_guard.py`.
- **Învățare continuă în fiecare zi:** în primele 3 luni (12 săptămâni) rulează pe Alpaca Paper și învață zilnic din fiecare trade (`autopsy.py` + `daily_learner.py` + `meta_label.py`) până devine cât mai profitabil; abia după Poarta 2 se trece pe bani reali.

Proprietarul nu știe programare: agentul face tot, proprietarul aprobă. Cu el vorbești în română simplă,
fără jargon; când trebuie să facă ceva, îi dai pași click cu click.

## Stack

| Parte | Tehnologie |
|---|---|
| Bot | Python 3.12, uv, ruff, pytest (offline, fără internet în teste) |
| Date | yfinance (istoric lung), Alpaca Market Data feed IEX (recent), Finnhub (earnings, știri) |
| Broker | Alpaca, prin `alpaca-py`. Paper întâi. Live doar după Poarta 2 (etapa 10) |
| AI | Gemini prin `google-genai`; modelul din `GEMINI_MODEL` (Flash-Lite, free tier) |
| Rulare | GitHub Actions programat (fără server propriu) |
| Stare | fișiere CSV/JSON în `state/`, pe branch-ul git `state` |
| Dashboard | Next.js pe Vercel Hobby (proiect separat `theo-trading-bot`) |
| Alerte | Telegram |

## Structura (țintă; se creează pe parcursul etapelor)

| Folder | Conținut |
|---|---|
| `src/config.py` | setările din `.env` / variabile de mediu |
| `src/data/` | date de piață, cache, validare, `drop_incomplete_bar` |
| `src/indicators.py` | indicatori în pandas pur (fără TA-Lib) |
| `src/strategies/` | S1 Trend Breakout, S2 Momentum Rotation, S3 RSI-2 Pullback, S4 MACD + EMA200 (funcții pure) |
| `src/backtest/` | backtester bar-cu-bar, walk-forward, Monte Carlo, test cu intrări aleatoare |
| `src/risk/guard.py` | regulile de risc hard-codate (NU se modifică fără aprobare) |
| `src/broker/` | adaptorul Alpaca (paper/live), idempotență, reconciliere, liquidate_all |
| `src/ai/` | `veto.py` (știri), `autopsy.py` (post-mortem) |
| `src/alerts/` | Telegram |
| `.github/workflows/` | `ci.yml`, `signals.yml`, `execute.yml`, `kill.yml`, `watchdog.yml` |
| `dashboard/` | Next.js, o singură pagină |
| `config/` | universul de acțiuni, parametrii strategiilor |
| `reports/` | `gate1.md`, `gate2.md`, `weekly/` |
| `docs/` | `PLAN.md` (specificațiile etapelor), `DECISIONS.md`, `handoff/` |
| `scripts/` | `set_keys.sh`, `check.sh`, `check_fast.sh`, utilitare |

## Comenzi

- Cheile: proprietarul rulează `bash scripts/set_keys.sh` (scrie `.env`). Nu ceri niciodată cheile în chat.
- Verificare rapidă: `scripts/check_fast.sh` · completă: `scripts/check.sh` (identică cu CI).
- GitHub: `gh` (proprietarul e logat). Vercel: `vercel` CLI. Secretele ajung în GitHub cu `gh secret set`
  și în Vercel cu `vercel env add`, citite din `.env` — niciodată scrise în cod, în commit-uri sau în chat.

## Convenții

- Cod și nume în engleză; comentarii scurte; tot ce vede proprietarul (rapoarte, dashboard, Telegram) în română.
- Orice decizie are motivul salvat (ce regulă, ce valori ale indicatorilor), ca dashboard-ul să explice „de ce”.
- Un parametru de strategie se schimbă doar cu backtest nou + Poarta 1 din nou + notă în `docs/DECISIONS.md`.
- Testele nu folosesc internetul; datele de test stau în `tests/fixtures/`.

## Interdicții (nu se schimbă fără acordul proprietarului)

1. Date din viitor (look-ahead): indicatorii doar pe bare închise; execuția la Open-ul barei următoare.
2. Modificarea `src/risk/guard.py` sau a constantelor lui.
3. `TRADING_MODE=LIVE` fără `LIVE_APPROVED.md` scris de proprietar și `reports/gate2.md` = PASS.
4. Ordin fără stop-loss la broker; lărgirea unui stop; averaging down; martingale; crypto (în Faza B sunt permise Long + Short + levier 1×/2× conform D31).
5. Secrete în cod, în commit-uri, în loguri sau în chat. `.env` nu se urcă niciodată pe GitHub.
6. Optimizarea parametrilor până „trece” Poarta 1. Maximum 2 iterații documentate, apoi strategia se abandonează.
7. AI-ul (Gemini) nu generează semnale, nu mărește poziții și nu schimbă reguli.

## Cine face ce

| Etapă | Agent |
|---|---|
| 0 Fundația (repo, uv, CI) | Oricare (Claude Code sau Antigravity); fișierele de reguli sunt deja scrise |
| 1 Date | Antigravity |
| 2 Backtester | **Claude Code** |
| 3 Strategii + Poarta 1 | **Claude Code** |
| 4 Risk guard | **Claude Code** |
| 5 Broker Alpaca paper | **Claude Code** |
| 6 Stare, veto, post-mortem | Antigravity |
| 7 Rulare zilnică + Telegram | Antigravity, apoi review Claude Code |
| 8 Dashboard | Antigravity |
| 9 Review, Poarta 2, fiscal | Antigravity |
| 10 Bani reali | **Claude Code** |

### Împărțirea pentru Faza B (Day Trading SPY/QQQ pe Alpaca Paper)

**Decizie obligatorie a proprietarului (4.11.2026):**
- Botul de pe **Alpaca Paper (contul demo)** se construiește **până la capăt (B3 → B4 → B5 → B6c)** și se pune în
  funcțiune pe contul Paper, **indiferent dacă B3 trece sau nu Poarta 1 B** (rezultatul Poarta 1 B se notează onest în
  `reports/gate1_daytrading.md`, dar NU oprește construcția botului Paper; doar banii reali rămân blocați până la Poarta 2).
- **Fără limită de număr de tranzacții pe zi:** botul poate executa oricâte tranzacții valide apar într-o zi pe SPY/QQQ
  (regula PDT e eliminată pe acțiuni SUA, iar pe Paper comisionul e 0; singura restricție e max 1 poziție deschisă
  simultan pe același simbol).
- **Învățare zilnică automată din greșeli:** în fiecare zi, după închiderea tranzacțiilor, botul:
  1. Generează lecția din fiecare tranzacție pierzătoare sau câștigătoare (`src/ai/autopsy.py`).
  2. Își re-antrenează / actualizează filtrul ML (`src/ai/meta_label.py` + `src/ai/daily_learner.py`) pe istoricul
     cumulat + tranzacțiile noi, ajustând probabilitățile ca să evite tiparele care au produs pierderi.
  3. Salvează totul în `state/` (pe branch-ul `state`) ca proprietarul să vadă în timp real în **Dashboard** ce a
     tranzacționat și ce a învățat azi.
- **Deploy obligatoriu în Git și în Vercel după fiecare etapă:** la finalul fiecărei etape se face commit + push +
  PR unit în `main` ȘI deploy în Vercel (`cd dashboard && vercel --prod --yes`).

Proprietarul folosește agenții în cascadă, în funcție de limita disponibilă:
1. **Claude Code (Opus 5.5 + sub-agenți Haiku):** rulează pe **B3** (strategiile D1, D1b, D2 + raportul B3).
2. **Antigravity pe Gemini 4 Argon (High) + sub-agenți `flash_lite`:** preia imediat după ce termină Claude Code (B4, B5, B6c), cât timp are usage.
3. **Antigravity pe Gemini 3.8 Flash (High) sau Codex pe GPT Go (Luna 6 High):** continuă orice pas rămas (B4, B5, B6c, B7), urmând mecanic rețetele date „mură în gură” în **`docs/GHID_EXECUTIE_AGENTI.md`**.

| Sub-pas Faza B | Agent permis | Rețeta pas cu pas |
|---|---|---|
| **B0** Verificare broker + date | Gata (Claude Code) | `docs/DECISIONS.md` (D23, D24) |
| **B1** Date 1 minut + model costuri | Gata (Antigravity) | `reports/b1_date.md` (D25, D26) |
| **B2** Motor backtester intraday | Gata (Claude Code) | `src/backtest/intraday_engine.py` (D27) |
| **B3** Strategiile D1, D1b, D2 + raport Poarta 1 B | Claude Code / Argon 4 | `docs/PLAN_DAYTRADING.md` + `reports/gate1_daytrading.md` (NU oprește Faza B pe Paper!) |
| **B4** Filtru ML + Învățare zilnică din greșeli | **Orice agent** (Argon 4, Gemini 3.8 Flash, Codex Luna 6) | `docs/GHID_EXECUTIE_AGENTI.md` · Secțiunea 4 |
| **B5** Risk Guard intraday + Broker Alpaca Paper | **Orice agent** (Argon 4, Claude Code, Gemini 3.8 Flash, Codex) | `docs/GHID_EXECUTIE_AGENTI.md` · Secțiunea 5 |
| **B6a** Dashboard Next.js pe Vercel | Gata (Antigravity) | `https://theo-trading-bot.vercel.app` |
| **B6b** Alerte Telegram în română | Gata (Antigravity) | `src/alerts/telegram.py` |
| **B6c** Botul live pe Alpaca Paper + Învățare zilnică + Dashboard live | **Orice agent** (Argon 4, Gemini 3.8 Flash, Codex Luna 6) | `docs/GHID_EXECUTIE_AGENTI.md` · Secțiunea 6 |
| **B7** Monitorizare Paper + Poarta 2 | **Orice agent** (Argon 4, Gemini 3.8 Flash, Codex Luna 6) | `docs/PLAN_DAYTRADING.md` |

## Regula „Mură în gură” pentru modele rapide (obligatorie)

Când un agent (în special Claude Code) termină o etapă și predă ștafeta în `PROGRESS.md` către o etapă pe care o poate
face Gemini Flash sau Codex / GPT Go, secțiunea **„Pasul următor exact”** din `PROGRESS.md` TREBUIE să conțină:
1. **Fișierele exacte** care trebuie create sau modificate (ex. `src/ai/meta_label.py`, `tests/test_meta_label.py`).
2. **Semnăturile exacte** ale funcțiilor (nume, parametri, ce returnează) și ce funcții existente trebuie importate.
3. **Ce calculează exact** (formula matematică fără echivoc, fără ca agentul următor să fie nevoit să ghicească).
4. **Comanda exactă de test** (`uv run pytest tests/test_... -q` și `bash scripts/check.sh`).

## Protocolul de lucru (pentru orice agent AI)

a. **La start** citești `AGENTS.md`, `PROGRESS.md` și secțiunea etapei curente din **`docs/GHID_EXECUTIE_AGENTI.md`** (plus `docs/PLAN_DAYTRADING.md`).
b. **Lucrezi pe branch-ul etapei** (`etapa-<N>-<nume>`), creat din `main` actualizat.
c. **După fiecare sub-pas** actualizezi `PROGRESS.md` (cu pasul următor exact), faci commit și push.
d. **O etapă e gata** doar cu testele verzi local (`scripts/check.sh`) și pe CI. Apoi PR spre `main`, unit după CI verde.
e. **Deciziile tehnice** le iei singur și le notezi în `docs/DECISIONS.md` (D1, D2…). Îl întrebi pe proprietar doar pentru
   bani, chei, conturi, acțiuni ireversibile sau orice ține de risc.
f. **La final raportezi** în română simplă, maximum 5 rânduri: ce ai făcut, ce urmează, ce trebuie să facă el.
g. **Predare continuă.** Lucrul se poate opri oricând. După fiecare sub-pas, totul e pe GitHub și `PROGRESS.md` e la zi.
h. **Cuvinte-cheie.** „limită” sau „predare” → execuți imediat `docs/handoff/PREDARE.md`. „preia” → `docs/handoff/PRELUARE.md`.
   „review etapa X” → citești diff-ul branch-ului etapei X față de `main`, verifici interdicțiile și testele, raportezi
   problemele și le repari doar pe cele clare. Scurtături: în Claude Code `/preia`, `/predare`; în Antigravity și Codex
   skill-urile `preia` și `predare` din `.agents/skills/`.

## Economie de usage (obligatoriu)

1. **Un sub-pas = o conversație.** La final: verificarea rapidă, `PROGRESS.md`, commit, push, apoi scrii doar:
   „Sub-pasul X e gata. Deschide o conversație nouă și scrie «preia».”
2. **Citești doar ce-ți trebuie.** Cauți cu `grep`/`rg`; nu citești integral fișiere de peste ~300 de rânduri, lockfile-uri sau loguri.
3. **Teste țintite** în timpul lucrului; `scripts/check.sh` complet o singură dată, înainte de PR.
4. **Rezultate lungi** (backtest, build) se scriu în `.cache/`; citești doar ultimele rânduri.
5. **Editări punctuale**, fără rescrieri de fișiere întregi pentru schimbări mici.
6. **Delegare inteligentă pe modele ieftine (economie de usage):**
   - Pentru sarcini simple sau voluminoase (descărcat/extras text dintr-un PDF sau de pe web, căutat într-un fișier mare,
     verificat formatări), agentul principal (Opus / Pro) **comandă un sub-agent ușor și ieftin**: **`haiku`** în Claude Code,
     respectiv **`flash_lite` / `flash`** în Antigravity (`invoke_subagent(..., Model="flash_lite")`), care returnează doar
     rezumatul scurt (10–20 de rânduri).
   - Astfel, modelul mare își consumă limita DOAR pe codul matematic greu și pe decizii, fără să-și încarce contextul.
   - Sunt interzise doar sub-agenții grei (Opus/Pro) lansați inutil pentru explorări largi ale repo-ului.
7. **Scripturile grele cu internet** (descărcarea a 20 de ani de date, walk-forward) le rulezi o dată; rezultatul se salvează.
