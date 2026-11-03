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
