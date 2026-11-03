# Decizii

Numerotate D1, D2…: decizia, motivul, data. Orice schimbare de parametru de strategie se notează aici.

- **D1 (3.11.2026)** Piață: acțiuni SUA large cap, daily, long-only. Fără crypto, CFD, levier, short. Motiv: costuri mici,
  date gratuite, risc controlabil pe un cont mic.
- **D2 (3.11.2026)** Broker: Alpaca paper pentru dezvoltare (API bun, bracket orders cu stop pe server). Live: Alpaca dacă
  acceptă rezidenți din România, altfel Trading 212 Invest (stop gestionat de bot); IBKR doar peste ~2.000 €.
  Motiv: XTB și-a închis API-ul (14.03.2025); T212 live acceptă prin API doar ordine Market.
- **D3 (3.11.2026)** Rulare pe GitHub Actions, fără server propriu: strategiile daily + stopul la broker nu cer un proces 24/7.
- **D4 (3.11.2026)** AI doar ca veto pe știri și post-mortem (Gemini Flash-Lite, free tier, proiect Google separat).
  Motiv: dovezile despre LLM-uri sunt pe reacția la știri, nu pe predicția prețului din serii numerice.
- **D5 (3.11.2026)** Capital: cont paper separat „TRADING” cu 500 $ și `BOT_CAPITAL=500` ca plafon în guard.
- **D6 (3.11.2026)** Cheia Finnhub e comună cu alt proiect al proprietarului (nu rulează în același timp). Botul face
  puține apeluri, o dată pe zi, cu reîncercare la HTTP 429. Dacă cheia se regenerează, se schimbă în ambele proiecte.
- **D7 (3.11.2026)** Țintă: bate buy-and-hold S&P 500 ajustat la risc, după costuri (Poarta 1). Altfel proiectul se oprește.
- **D8 (3.11.2026)** Backtester: stop = prețul de intrare efectiv (Open t+1 + costuri) − `stop_distance`; R-ul include
  costurile, deci o ieșire pe stop pierde puțin peste 1R. Mărimea se calculează pe equity-ul de la Open-ul zilei de
  execuție, fără levier (limitată și de cash). Motiv: așa va lucra și botul live (ordinul pleacă după deschidere).
- **D9 (3.11.2026)** Sizing-ul stă temporar în `src/backtest/sizing.py`, stub cu aceeași semnătură ca `size_position`
  din etapa 4; la etapa 4 motorul importă din `src/risk/guard.py` și stub-ul dispare. Implicit acțiuni fracționare
  (minim 1 $ pe ordin); opțiunea `whole_shares` rămâne pentru cazul în care Alpaca nu permite bracket pe fracționare
  (se verifică la etapa 5).
- **D10 (3.11.2026)** Walk-forward: fiecare fereastră de test pornește cu capitalul inițial și închide pozițiile în
  ultima zi; curba OOS = randamentele zilnice ale ferestrelor, înlănțuite; ultima fereastră poate fi parțială.
  Indicatorii se calculează pe tot istoricul (sunt cauzali, verificat de detectorul de look-ahead).
- **D11 (3.11.2026)** Monte Carlo: drawdown-ul din 1.000 de reamestecări ale ordinii tranzacțiilor; randamentul din
  1.000 de reeșantionări cu înlocuire (o reamestecare nu schimbă randamentul final). Testul aleator: același număr de
  intrări pe simbol, în zile și ordine aleatoare; aceleași ieșiri, stopuri și sizing.
- **D12 (3.11.2026)** Convenții: ATR, RSI, ADX (Wilder) și EMA pornesc de la media simplă a primelor n valori;
  Sharpe cu rata fără risc 0, anualizat cu √252; CAGR pe zile calendaristice.
- **D13 (3.11.2026)** Strategie candidată nouă S4 MACD + EMA200 (după canalul TradingLab), adaptată la daily și
  acțiuni, testată la Poarta 1 cu aceleași praguri. Plafon: maximum 4 strategii candidate, ca să nu crească șansa
  ca una să treacă din noroc (data snooping). Cerută de proprietar.
- **D14 (3.11.2026)** Interpretări la S1–S4 (etapa 3a), fără optimizare: S1 compară Close cu maximul High-urilor din
  cele 55 de zile anterioare (Donchian shiftat) și iese sub minimul Low-urilor din cele 20 anterioare. S2: prima zi de
  tranzacționare a lunii = prima bară a lunii în calendar (prima bară a datelor nu contează); intrări = primele 5
  după momentum dintre cele cu Close > SMA200; ieșire dacă locul în clasamentul întregului univers e peste 10 sau
  lipsește. S4: minimul pe 10 zile include bara curentă; stopul se aplică de la prețul real de intrare (D8).
  Când mai multe intrări vin în aceeași zi, ordinea e dată de `score` (S1 forța breakout-ului în ATR, S2 momentum,
  S3 RSI cel mai mic, S4 histograma MACD în ATR); nu e un parametru optimizat. Parametrii sunt validați strict
  (cheie necunoscută în YAML → eroare); citirea YAML-ului cu `pyyaml`.
- **D15 (3.11.2026)** Poarta 1 se rulează în două variante, la `BOT_CAPITAL=500`: acțiuni fracționare și acțiuni
  întregi (`whole_shares=True`); `reports/gate1.md` arată ambele. Motiv: dacă Alpaca nu acceptă bracket (stop la
  broker) pe fracționare, live se pot cumpăra doar acțiuni întregi și multe titluri scumpe ar fi sărite. Decis de
  proprietar.
- **D16 (3.11.2026)** Date (etapa 3b): validarea OHLC tolerează diferențe relative sub 1e-9 (rotunjiri float din
  ajustarea yfinance, de ex. high=28.8222541809082 vs close=28.822254180908203), altfel 70 de simboluri erau
  respinse. Universul: BK → BNY (BNY Mellon și-a schimbat simbolul, aceeași companie). Simbolurile cu punct se cer
  la yfinance cu cratimă (BRK.B → BRK-B); în cache și la Alpaca rămân cu punct.
- **D17 (3.11.2026)** Regulile de evaluare ale Porții 1 (`src/backtest/gate1.py`), fixate înaintea rulării complete:
  OOS = walk-forward 3 ani istoric / 1 an test pe 2006–azi; SPY cumpărat și ținut pe aceeași perioadă OOS, cu
  aceleași costuri. Criteriul 1 la S2 numără poziții-lună (sfârșituri de lună peste care e ținută poziția, minimum 1).
  Criteriul 5: fiecare parametru pe rând la ×0.8 și ×1.2, restul la bază; parametrii întregi se rotunjesc, iar dacă
  rotunjirea dă tot valoarea de bază se mută cu 1 (RSI 2 → 1 și 3); PF-ul OOS trebuie să fie > 1.1 în toate.
  Criteriul 6: 500 de rulări cu intrări aleatoare pe perioada OOS (backtest continuu), comparate după Sharpe
  (aceeași măsură ajustată la risc ca ținta D7); celelalte măsuri apar doar informativ. Criteriul 7 pe tranzacțiile
  OOS. Se rulează la 500 $, în ambele variante (D15). Graficele cer `matplotlib` (dependență doar de dezvoltare).
- **D18 (3.11.2026)** Iterația 1 după Poarta 1 = FAIL. Cerută de proprietar, care a lăsat alegerea agentului. O
  singură schimbare, la o singură strategie: S4 primește filtrul de piață SPY > SMA(200), același ca la S1, S2 și
  S3 (parametru nou `spy_filter: 200`, aceeași valoare ca la celelalte, nu căutată). Restul parametrilor S4 rămân
  la fel. Motiv: S4 are cel mai bun Sharpe OOS (0.75) și trece criteriile 1, 3, 4, 5 și 7. Ipoteza: o încrucișare
  MACD sub zero e o corecție într-un trend sănătos când piața urcă, dar mai des un rally care eșuează când piața
  scade (SPY sub SMA200); majoritatea anilor OOS negativi ai S4 (2015, 2016, 2018, 2022) au avut piața mult timp
  sub SMA200. Alegerea e influențată de rezultatele văzute, deci: o singură schimbare, aceleași 7 criterii și
  praguri, ambele variante (D15), testul ±20% include și noul parametru. Regula de oprire, fixată acum: dacă S4 cu
  filtru pică, nu mai facem iterații (nici la S1–S3) și proiectul se oprește (D7). Dacă trece, PASS-ul rămâne
  suspect (survivorship bias, alegere după rezultate) și se confirmă doar la Poarta 2 (12 săptămâni paper).
- **D19 (3.11.2026)** Rezultatul iterației 1 (D18, `reports/gate1_iteratia1.md`): S4 cu filtrul SPY pică Poarta 1 în
  ambele variante. Fracționare: criteriile 2 (Sharpe 0.74 vs 0.85 SPY) și 6 (bate 84% din intrările aleatoare, nu
  95%); acțiuni întregi: criteriile 2, 3, 4, 5 și 6. Filtrul aproape nu schimbă rezultatul (Sharpe 0.75 → 0.74).
  Conform regulii de oprire fixate în D18 înainte de rulare: nicio altă iterație, proiectul se oprește (D7). Etapele
  4–10 nu se mai fac. `reports/gate1.md` rămâne rezultatul de bază; `scripts/gate1.py --iteratia1` reproduce iterația.
- **D20 (3.11.2026)** Proprietarul a ales să continue cu o **Fază B: day trading pe CFD, doar pe demo** (opțiunea 1
  după cercetarea din 3.11; raportul: „Strategii sistematice cu edge real”). Excepții de la D1 doar pentru Faza B:
  CFD pe US500/US100 și expunere noțională de maximum 2× equity, intraday, închis la final de zi. Bani reali doar după
  Poarta 2. Proprietarul a fost informat că 77–81% din conturile retail CFD pierd bani și că ținta de „100 $/săptămână
  din 500 $” (+20%/săptămână) nu e realistă. Specificația: `docs/PLAN_DAYTRADING.md`.
- **D21 (3.11.2026)** După cercetările Gemini și ChatGPT Deep Research aduse de proprietar: se adaugă D1b (ieșire
  VWAP & Ladder, Maróy 2025, cu parametri fixați înainte), filtrul ML devine meta-labeling cu Triple Barrier și
  purged CV, veto FOMC + veto de spread, Capital.com devine brokerul candidat (Open API cu demo, verificat în
  documentația oficială). Respinse din acele rapoarte: regulile „VWAP ± 1,2×ATR” (nu sunt din paper), strategia
  Gao et al. (edge dispărut după 2013), front-running pe ETF-uri cu levier (doar rezultate brute până în 2011),
  XTB API (închis). N total = 9.
- **D22 (3.11.2026)** Faza B se face pe Alpaca Paper (SPY/QQQ), nu pe CFD: proprietarul are deja contul, iar
  costurile pe acțiuni sunt mult sub cele CFD (replicarea ORB a murit tocmai din spread-ul CFD). CFD (Capital.com)
  rămâne alternativa pentru live. Cu 500 $ live pe Alpaca: doar long-only, fără levier (short/levier cer 2.000 $).
- **D23 (3.11.2026, B0)** Date de 1 minut pe planul gratuit Alpaca (verificat cu `scripts/probe_alpaca_b0.py`,
  doar citire): feed **SIP** pentru SPY și QQQ de la **ianuarie 2016** (2015 lipsește complet), sesiuni complete
  (391 de bare 9:30–16:00 ET în 2016, 2020, 2025), dar fără ultimele 15 minute („subscription does not permit
  querying recent SIP data”). Feed **IEX** doar de la 27.07.2020, cu bare lipsă (QQQ 384/390), dar permis în timp
  real. Decizie: istoricul din B1 se ia din SIP, 2016-01-04 → azi; fereastra Porții 1 B devine **2016–azi** în loc
  de 2015–azi (lipsă de date, nu alegere; ≥ 300 de tranzacții OOS rămân ușor de atins). În demo (B6) barele recente
  vin din IEX: VWAP-ul și volumul IEX diferă de cele consolidate (SIP), deci B1 măsoară diferența SIP vs IEX pe
  2020-07 → azi înainte ca D1 să folosească VWAP-ul live.
- **D24 (3.11.2026, B0)** Short pe Alpaca Paper: SPY și QQQ sunt `shortable` și `easy_to_borrow`, marjă de
  menținere 30%, dar contul paper de 500 $ are `shorting_enabled = False` și `multiplier = 1` (Alpaca cere
  ≥ 2.000 $ equity pentru marjă și short, și pe paper). Deci, cu 500 $, pe paper merge doar long, fără levier.
  Backtestul (B2–B3) testează oricum ambele direcții. Pentru short și expunere 2× pe demo, proprietarul ar trebui
  să reseteze contul paper la ≥ 2.000 $ (decizia lui, cerută la finalul B0); altfel D1/D2 rulează pe demo long-only.
  **Decis de proprietar (3.11.2026): contul paper rămâne la 500 $**, deci demo-ul (B6–B7) rulează D1/D1b/D2 doar
  long, fără levier, la fel ca live-ul cu 500 $ (D22). Consecință pentru B3: Poarta 1 B se fixează, înainte de rulare,
  pe varianta care chiar va tranzacționa (long-only), cu testul aleator adaptat; long+short rămâne doar informativ.
- **D25 (3.11.2026, B1)** Datele de 1 minut și modelul de costuri pentru Faza B:
  - Calendarul NYSE (sărbători, închideri la 13:00) vine din pachetul `exchange-calendars` (offline, testabil).
    Se păstrează doar barele care încep în sesiune: 9:30 ≤ t < închidere (390 de bare pe zi, 210 la 13:00).
  - Prețuri brute (`Adjustment.RAW`): SPY și QQQ n-au avut split-uri din 2016, iar pozițiile se închid în aceeași
    zi, deci dividendele nu contează. Istoricul se oprește la ultima sesiune închisă complet (nu o zi parțială).
  - Cache: `data/cache/minute/<FEED>/<SIMBOL>/<an>.parquet` (nu în git), scris de `scripts/download_minute.py`.
  - Costuri pe fiecare intrare și ieșire, în dolari pe acțiune (`src/backtest/intraday_costs.py`):
    acțiuni SPY/QQQ = jumătate de spread 0,005 $ + slippage 0,01 $ (comision 0; taxele FINRA, sub 0,0002 $/acțiune,
    intră în slippage), deci 0,03 $ dus-întors; CFD = US500 0,8 puncte și US100 2,5 puncte, convertite în unități
    SPY/QQQ cu raportul indice/ETF (S&P 500 ≈ 10,0 × SPY, Nasdaq-100 ≈ 40,8 × QQQ): 0,08 $ / SPY și 0,061 $ / QQQ
    pe parte. Test de stres ×1,5. Tranzacțiile cu riscul inițial < 2× costul dus-întors se sar.
    Slippage-ul pe acțiuni e ales prudent (de 2× jumătatea de spread), ca un stop executat la piață să nu pară gratis.
- **D26 (3.11.2026, B1)** Validarea datelor de 1 minut și comparația SIP vs IEX (`scripts/b1_data_report.py`,
  `reports/b1_date.md`):
  - **SIP (2016-01-04 → 2026-11-02, 2.724 sesiuni NYSE):** 0 zile lipsă, 0 dubluri, 0 bare în afara sesiunii, 0 bare
    cu OHLC incoerent, 21 de închideri la 13:00 recunoscute. Câte o singură sesiune cu < 95% bare: SPY pe 2019-08-12
    (360/390 bare, se oprește la 15:31 ET) și QQQ pe 2016-02-22 (340/390 bare). În B2, ieșirea la final de zi se face
    la ultima bară disponibilă a sesiunii, iar verificările de la `:00`/`:30` folosesc ultima bară închisă disponibilă.
  - **IEX (2020-07-27 → 2026-11-02, 1.576 sesiuni):** 1 zi lipsă complet (`2025-03-10`) și 161 (SPY) / 768 (QQQ)
    sesiuni cu < 95% bare (acoperire 98,3% din minutele SIP pe SPY și 92,1% pe QQQ; cotă de volum 2,0% SPY și 1,4% QQQ).
  - **Diferența IEX minus SIP (1.575 zile comune):**
    - Închidere pe minut (`close_bps`): SPY mediană 0,365 pb (~0,02 $), p95 2,266 pb, bias -0,012 pb; QQQ mediană
      0,692 pb (~0,035 $), p95 4,069 pb, bias -0,014 pb.
    - VWAP cumulativ de sesiune (`vwap_bps`): SPY mediană 1,241 pb (~0,07 $), p95 6,888 pb (~0,41 $), max 79,4 pb;
      QQQ mediană 2,311 pb (~0,12 $), p95 11,778 pb (~0,59 $), max 145,7 pb (aproape identic și după 10:00 ET).
  - **Consecință pentru B3 și B6 (demo):** prețul pe minut IEX e foarte apropiat de SIP, dar VWAP-ul cumulativ IEX
    deviază la p95 cu 7–12 pb din cauza volumului mic de pe o singură bursă. În B3 se verifică pe 2020–2026 dacă D1/D1b
    își păstrează rezultatul când semnalele vin din IEX; în B6 (live pe demo), VWAP-ul de sesiune se poate ancora din
    SIP pentru partea de zi mai veche de 15 minute + IEX doar pe ultimele 15 minute (permis pe planul gratuit).
- **D27 (3.11.2026, B2)** Backtesterul intraday (`src/backtest/intraday_engine.py`, `fomc.py`, `intraday_metrics.py`):
  - Semnal pe bara de 1 minut închisă `t`, execuție la Open-ul barei următoare a simbolului, în aceeași sesiune.
    Stop și țintă pe High/Low; ambele atinse în aceeași bară → stop (worst case); gap peste stop → ieșire la Open.
    La ultima bară disponibilă a sesiunii (15:59, 12:59 la închiderile de la 13:00, mai devreme dacă lipsesc bare,
    D26) totul se închide la Close (ordin market-on-close). Ordinele nu trec peste noapte; semnalele de pe ultima bară
    se ignoră. O singură poziție pe simbol; stop-ul doar se strânge (trailing), nu se lărgește niciodată.
  - Sizing: `size` din semnal (ținta de volatilitate, ca fracțiune din equity) sau risc 0,5%, plafonat la expunerea
    totală `max_exposure` (2× equity; 1× pentru long-only fără marjă, D24); plafon opțional de risc pe tranzacție.
    Riscul rezultat se raportează pe fiecare tranzacție (`risk_pct`), rezultatul în R față de Open-ul de intrare.
    Ținta parțială pentru D1b: `target_fraction` (o parte la țintă, restul pe stop sau la final de zi).
  - Veto FOMC: 88 de anunțuri în sesiune 2016–2026 (14:00 ET; plus anunțul neprogramat din 2020-03-03, 10:00),
    2021–2026 verificate pe federalreserve.gov la 3.11.2026, 2016–2020 din calendarele istorice ale Fed. Fără intrări
    cu Open-ul între 30 de minute înainte și 30 de minute după anunț. Veto-ul de spread (2× spread-ul tipic) rămâne
    pentru live: backtestul nu are cotații bid/ask.
  - Testul cu direcție aleatoare: fiecare tranzacție se reia long și short din aceeași bară și același Open, cu
    stop fix la distanța inițială (oglindit) și ieșire la stop sau la închiderea sesiunii, pentru ambele direcții.
    Prima variantă păstra ora reală de ieșire, aleasă de stop-ul direcției originale, și dezavantaja direcția opusă:
    o strategie cu direcție la întâmplare „bătea” testul în 99% din rulări. După corecție, 8 strategii aleatoare pe
    SPY+QQQ 2016–2026 dau între 20% și 89% (niciuna ≥ 95%). Pentru long-only (D24): moneda se aruncă pe candidații
    rulării long+short și se păstrează doar long-urile.
  - Metrici: expectancy în R cu t-stat unilateral (aproximare normală, ≥ 300 de tranzacții) și p ajustat Bonferroni
    ×9; Deflated Sharpe pe randamentele zilnice cu N = 9 și varianța Sharpe-urilor 1/(T−1) implicit (B3 o poate da
    din cele N încercări reale); randament pe ani, zile cu pierdere > 2%, PF, drawdown.
  - Limita de pierdere zilnică (−2%) și KILL la −15% nu sunt în motor: țin de risk guard-ul din B5; B3 le vede în
    raport prin zilele cu pierdere > 2% și drawdown. Viteză: 2016–2026, SPY+QQQ (1,06 mil. bare) ≈ 2 s pe rulare.
