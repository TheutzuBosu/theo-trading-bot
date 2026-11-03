# Theo Trading Bot: instrucțiuni pentru agenți AI

Fișierul acesta e sursa unică de reguli pentru orice agent (Claude Code, Antigravity, Codex, Gemini).
Citește-l integral înainte de orice acțiune.

## Scop

Un bot de trading automat, **personal**: tranzacționează doar contul propriu al proprietarului, cu banii lui.
Nu se dă, nu se vinde și nu se conectează la conturile altor persoane (asta ar cere autorizare ASF).
Proiectul e complet separat de Market Lens: alt folder, alt repo, alte chei (excepție: cheia Finnhub, D6).

- Acțiuni SUA large cap, **daily, long-only**. Fără crypto, fără CFD, fără levier, fără short.
- Matematica decide, risk guard-ul blochează, AI-ul poate doar să spună „nu” (veto pe știri) și să explice.
- Ordinea: backtest (Poarta 1) → 12 săptămâni paper (Poarta 2) → bani reali, crescuți treptat.
- Ținta nu e „face profit”, ci „bate buy-and-hold S&P 500 ajustat la risc, după costuri”. Dacă nu, ne oprim.

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
4. Ordin fără stop-loss la broker; lărgirea unui stop; averaging down; martingale; levier; short; crypto.
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

O etapă marcată Claude Code nu o face alt agent: dacă Claude e la limită, se lucrează la o etapă Antigravity
(de ex. 8 pe date de exemplu) sau se așteaptă.

## Protocolul de lucru (pentru orice agent AI)

a. **La start** citești `AGENTS.md` și `PROGRESS.md`, apoi din `docs/PLAN.md` doar regulile comune și secțiunea etapei tale.
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
6. **Fără sub-agenți** și fără explorări largi ale repo-ului.
7. **Scripturile grele cu internet** (descărcarea a 20 de ani de date, walk-forward) le rulezi o dată; rezultatul se salvează.
