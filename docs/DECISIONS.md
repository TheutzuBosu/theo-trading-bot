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
