# Faza B — Day trading pe CFD (doar demo) · decizia proprietarului D20

Proprietarul a cerut explicit un bot de day trading pe CFD-uri, testat și „antrenat” (D20). Regulile din `AGENTS.md`
rămân în vigoare, cu excepțiile din D20: CFD și levier limitat sunt permise, DAR doar pe cont **demo** până la
Poarta 2. Țintă onestă: a verifica dacă există un edge net de costuri, nu „100 $ pe săptămână”.

## Ce se tranzacționează și când

- Instrumente: SPY și QQQ pe Alpaca Paper (date de 1 minut din Alpaca Market Data). CFD pe US500/US100 doar ca
  variantă de cost în backtest și ca alternativă pentru live (vezi B0).
- Doar sesiunea cash din SUA (16:30–23:00 ora României). **Toate pozițiile se închid înainte de închiderea sesiunii**
  (fără swap peste noapte). Maximum 1 poziție deschisă pe instrument.

## Strategiile candidate (pre-înregistrate; nu se adaugă altele fără o decizie nouă în DECISIONS)

- **D1 · Intraday momentum „noise area”** (Zarattini, Aziz & Barbon 2024, „Beat the Market”, SSRN; autorii
  raportează 19,6%/an net, Sharpe 1,33 pe SPY 2007–2024 — rezultat al autorilor, neverificat independent).
  Implementezi regulile exact din paper (descarcă PDF-ul de pe SSRN/Concretum și citează secțiunile): banda de zgomot
  din mișcarea medie absolută de la deschidere din ultimele 14 zile, intrare doar la verificările de la :00 și :30 când
  prețul iese din bandă, stop trailing (bandă/VWAP), închidere la final de zi, sizing după volatilitate.
- **D1b · aceeași intrare ca D1, ieșire „VWAP & Ladder”** (Maróy 2025, SSRN 5095349): jumătate din poziție se
  închide la un prag de profit, restul la revenirea prețului la VWAP sau la final de zi. Autorul raportează Sharpe
  > 3, dar după optimizarea TUTUROR parametrilor, fără out-of-sample și fără costuri declarate. De aceea D1b se
  testează cu parametrii din paper-ul lui, fixați înainte de rulare, fără reoptimizare. Doar D1 și D1b; nicio altă
  variantă de ieșire (fiecare variantă în plus crește N).
- **D2 · Opening Range Breakout 5 minute** (Zarattini & Aziz 2023, „Can Day Trading Really Be Profitable?”). Folosit
  mai ales ca **martor**: o replicare independentă pe CFD-uri 2015–2026 a găsit că profitul brut dispare complet după
  spread și slippage (NQ +0,002R, restul negative). Dacă D1 nu face mai bine decât D2, D1 nu are edge real.

## „Antrenarea”, fără auto-înșelare

1. **Calibrare walk-forward:** cel mult 2 parametri pe strategie, recalibrați lunar pe fereastra de 2 ani anterioară,
   aplicați pe luna următoare. Se raportează doar rezultatul out-of-sample înlănțuit.
2. **Filtru ML de tip meta-labeling (opțional, doar dacă D1/D1b trece fără el):** López de Prado, „Advances in
   Financial Machine Learning” (2018). Regulile D1 dau direcția; un model mic (regresie logistică sau gradient
   boosting, scikit-learn, < 15 caracteristici luate DOAR din date disponibile la momentul semnalului: ora, distanța
   față de bandă și VWAP, volatilitatea recentă, gap-ul, randamentul overnight, ziua săptămânii, spread-ul estimat)
   estimează probabilitatea ca semnalul să fie câștigător. Etichete prin Triple Barrier (țintă, stop, final de zi),
   net de costuri. Validare cu purged / combinatorial purged cross-validation (embargo între antrenare și test).
   Pragul de probabilitate (de ex. 0,55) se fixează ÎNAINTE. Filtrul rămâne doar dacă îmbunătățește out-of-sample
   expectancy-ul net și Deflated Sharpe față de D1 fără filtru.
3. **Învățarea din demo:** jurnalul și post-mortem-ul (etapa 6) clasifică pierderile, dar orice schimbare de regulă
   trece prin backtest nou + DECISIONS. Botul nu își schimbă singur regulile și nici riscul.

## Modelul de costuri (obligatoriu în backtest)

Mărimea poziției urmează regula din paper (țintă de volatilitate), dar plafonată la expunere 2× equity; riscul pe
tranzacție rezultat se raportează. Spread + slippage pe fiecare intrare și ieșire, exprimate în puncte de indice: US500 0,8 puncte, US100 2,5 puncte
(din replicarea independentă), plus 0 comision. Tranzacțiile cu riscul inițial < 2× costul dus-întors se sar.
Rulezi și o variantă cu costurile ×1,5 (testul de stres).
Veto de evenimente (determinist): fără intrări cu 30 de minute înainte și 30 după anunțurile FOMC (calendarul oficial
Fed, hard-codat pe an) și fără intrări dacă spread-ul curent la broker depășește de 2× spread-ul tipic.

## Poarta 1 pentru Faza B (toate obligatorii; D1, D1b și eventual filtrul ML duc proiectul la N = 9 teste)

1. ≥ 300 de tranzacții out-of-sample, 2016–azi (date Alpaca de la 2016, D23), net de costuri.
2. Expectancy net ≥ +0,05R, cu t-stat ≥ 2,6 (corecție Bonferroni pentru N = 9), și pozitivă cu costurile ×1,5.
   Deflated Sharpe Ratio ≥ 0,95 calculat cu N = 9.
3. Bate testul cu **direcție aleatoare** (aceleași intrări, stopuri și ore, direcție aleasă la întâmplare; 1.000 de
   rulări) în ≥ 95% din rulări.
4. Profitabilă în ≥ 60% din ani; niciun an sub −15%.
5. Sharpe-ul anualizat al curbei OOS ≥ 1,0 la riscul de 0,5%/tranzacție.
6. Parametri ±20% → expectancy rămâne > 0.
7. D1 bate D2 (martorul).
Dacă nu trec toate: Faza B se oprește. Fără a doua iterație pe aceleași date.

## Reguli de risc pentru CFD (hard-codate; se pot doar înăspri)

Risc 0,5% din equity pe tranzacție; expunere noțională maximă 2× equity (sub plafonul ESMA de 20:1 pe indici);
pierdere zilnică maximă −2% → stop pe zi; drawdown −15% → KILL; stop-loss obligatoriu la broker; fără medierea
pierderilor, fără martingale; toate pozițiile închise automat înainte de finalul sesiunii.

## Broker și rulare

- **Sub-pasul B0:** pentru backtest și demo se folosește **Alpaca Paper** (contul și cheile există deja în `.env`),
  pe acțiunile SPY și QQQ, nu pe CFD-uri. Avantaj major: costuri mult mai mici decât pe CFD (comision 0, spread SPY
  de ~1 cent la ~600 $), iar regula PDT de 25.000 $ e eliminată din iunie 2026. Pe paper se testează ambele direcții
  (long și short). De verificat în B0 și notat în DECISIONS: datele istorice de 1 minut disponibile pe planul gratuit
  Alpaca (de la ce an), dacă paper-ul permite short pe SPY/QQQ și cu ce marjă.
  Limitare pentru bani reali (abia la etapa live): short-ul și orice levier cer cont de marjă, cu minimum 2.000 $;
  cu 500 $ se poate rula doar varianta long-only, fără levier. Dacă Alpaca nu acceptă cont live din România sau
  dacă se dorește levier mic cu 500 $, alternativa live e un CFD pe US500 la **Capital.com** (Open API cu demo:
  `https://demo-api-capital.backend-capital.com/`, cheie din Settings > API integrations cu 2FA; 10 cereri/s,
  sesiune de 10 minute), cu modelul de costuri CFD de mai sus. NU: XTB (API închis în martie 2025).
  Backtestul se raportează în ambele variante de cost: acțiuni SPY/QQQ și CFD US500/US100.
- Rularea: GitHub Actions întârzie prea mult pentru intraday. Botul rulează ca proces Python ușor pe PC-ul Linux al
  proprietarului (systemd, repornire automată, `MemoryMax=200M`) sau pe Mac în timpul sesiunii. Kill switch-ul și
  alertele Telegram rămân ca în planul principal.

## Etape

- **B0** broker + cont demo (Claude Code) · **B1** date de 1 minut SPY/QQQ 2016–azi (D23) + model de costuri (Antigravity)
- **B2** backtester intraday + testul cu direcție aleatoare (Claude Code) · **B3** D1, D2, walk-forward, raportul
  `reports/gate1_daytrading.md` (Claude Code) · doar dacă trece: **B4** filtrul ML · **B5** risk guard CFD + adaptor
  broker demo (Claude Code) · **B6** procesul live pe demo + Telegram + dashboard (Antigravity) · **B7** minimum 12
  săptămâni pe demo, apoi Poarta 2. Bani reali: doar după Poarta 2 și `LIVE_APPROVED.md`.

## Așteptare realistă (scrisă înainte de test)

Chiar dacă D1/D1b trece Poarta 1, la un cont de 500 $ cu expunere de maximum 2× costurile CFD consumă o parte mare
din fiecare tranzacție (ordin de mărime: ~1,5 puncte dus-întors pe US500 față de un stop de câteva zeci de puncte).
Estimarea de lucru pentru rezultatul net: între −2% și +2% pe lună. Scopul Fazei B este să afle dacă există un edge
net măsurabil, nu să producă venit.

## Surse care au format acest plan (3.11.2026)

- Cercetarea proprie: raportul „Strategii sistematice cu edge real” (anomalii după publicare, testare multiplă,
  forex/CFD, calendar și știri).
- Gemini Deep Research și ChatGPT Deep Research, verificate (D21): preluate Maróy 2025, meta-labeling, veto FOMC și
  spread; respinse afirmațiile neverificabile.
- Studii: Zarattini, Aziz & Barbon 2024 (D1); Maróy 2025 (D1b); Zarattini & Aziz 2023 + replicarea independentă pe
  CFD (D2, martor); Bailey & López de Prado (Deflated Sharpe); Harvey, Liu & Zhu (prag t); Lou, Polk & Skouras
  (de ce pozițiile intraday trebuie închise rapid); Barber et al., Chague et al. (realitatea day traderilor).
- Cărți: López de Prado, „Advances in Financial Machine Learning” (meta-labeling, Triple Barrier, purged CV);
  Kevin Davey, „Building Winning Algorithmic Trading Systems” (walk-forward, incubare pe demo înainte de bani reali);
  Robert Carver, „Systematic Trading” (reguli simple, puțini parametri, sizing după volatilitate).
- Videoclipuri, doar ca lecții de metodă: Steven Ace (backtester care nu poate trișa, test pe ani nevăzuți, testul
  cu moneda, demo înainte de bani), DaviddTech (incubare de 3 luni, oprire când edge-ul dispare). Clipurile cu
  profit în titlu („$102k”, „$3K/day”, „payout”) nu au fost folosite: fără dovezi verificabile.
