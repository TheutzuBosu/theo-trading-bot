# Raport Poarta 1 B — Day Trading Intraday SPY & QQQ (Faza B)

**Data rulării:** 4 noiembrie 2026  
**Fereastra OOS evaluată:** `2018-01-02 → 2026-10-30` (2.221 sesiuni NYSE, 106 luni)  
**Fereastra de calibrare inițială / warmup:** `2016-01-04 → 2017-12-29` (502 sesiuni NYSE)  
**Varianta judecată (D24, D29):** `SPY + QQQ`, `long_only=True`, `max_exposure=1.0`, acțiuni fracționare, `BOT_CAPITAL=500 $`, costuri `stock` (D25), veto FOMC (±30 min), `max_risk_per_trade=0.5%`, cel mult 50% din capital pe simbol.  
**Reguli și praguri pre-înregistrate:** `D29` și `D29b` în `docs/DECISIONS.md` (N = 9 încercări).

## 1. Verdict Poarta 1 B

**Verdict general Poarta 1 B (criteriile stricte din D29/D29b):** **PASS**

> **Notă operațională (Decizia proprietarului, 4.11.2026):** Indiferent de scorul Porții 1 B pe backtest, construim botul complet pe **Alpaca Paper** (`B4 → B5 → B6c`), unde nu se riscă niciun ban real, iar botul învață zilnic din greșeli (`autopsy.py`, `daily_learner.py`, `meta_label.py`). Doar trecerea la bani reali rămâne blocată de Poarta 2.

### D1 (calibrat lunar 24m) — **FAIL** (5/7 criterii îndeplinite)

| # | Criteriu | Valoare obținută | Prag D29/D29b | Status |
|---|---|---|---|---|
| 1 | Tranzacții OOS | 2046 | >= 300 | **PASS** |
| 2 | Expectancy net, t-stat, costuri ×1,5 și DSR | E[R]=+0.032R (t=3.50), E[R]×1,5=+0.028R, DSR=68.3% | E[R] >= +0.05R, t >= 2.6, E[R]×1,5 > 0, DSR >= 95% | **FAIL** |
| 3 | Testul cu direcție aleatoare (1.000 rulări) | 100.0% bătute | >= 95% | **PASS** |
| 4 | Consistență pe ani (2018–2026) | 66.7% ani pe plus, cel mai slab an -1.8% | >= 60% ani > 0 și niciun an < -15% | **PASS** |
| 5 | Sharpe anualizat OOS (√252) | 0.99 | >= 1.00 | **FAIL** |
| 6 | Stabilitate la ±20% pe parametri | 4/4 cu E[R] > 0 (minim +0.027R) | E[R] > 0 în toate variantele | **PASS** |
| 7 | Bate martorul D2 (ORB 5m) după Sharpe OOS | Sharpe 0.99 vs D2 0.42 | Sharpe > 0.42 | **PASS** |

### D1 (default L=14, m=1.0) — **FAIL** (6/7 criterii îndeplinite)

| # | Criteriu | Valoare obținută | Prag D29/D29b | Status |
|---|---|---|---|---|
| 1 | Tranzacții OOS | 1998 | >= 300 | **PASS** |
| 2 | Expectancy net, t-stat, costuri ×1,5 și DSR | E[R]=+0.032R (t=4.12), E[R]×1,5=+0.028R, DSR=86.3% | E[R] >= +0.05R, t >= 2.6, E[R]×1,5 > 0, DSR >= 95% | **FAIL** |
| 3 | Testul cu direcție aleatoare (1.000 rulări) | 100.0% bătute | >= 95% | **PASS** |
| 4 | Consistență pe ani (2018–2026) | 88.9% ani pe plus, cel mai slab an -0.7% | >= 60% ani > 0 și niciun an < -15% | **PASS** |
| 5 | Sharpe anualizat OOS (√252) | 1.18 | >= 1.00 | **PASS** |
| 6 | Stabilitate la ±20% pe parametri | 4/4 cu E[R] > 0 (minim +0.028R) | E[R] > 0 în toate variantele | **PASS** |
| 7 | Bate martorul D2 (ORB 5m) după Sharpe OOS | Sharpe 1.18 vs D2 0.42 | Sharpe > 0.42 | **PASS** |

### D1b (VWAP & Ladder #1, Maróy 2025) — **PASS** (8/8 criterii îndeplinite)

| # | Criteriu | Valoare obținută | Prag D29/D29b | Status |
|---|---|---|---|---|
| 1 | Tranzacții OOS | 1399 | >= 300 | **PASS** |
| 2 | Expectancy net, t-stat, costuri ×1,5 și DSR | E[R]=+0.303R (t=5.79), E[R]×1,5=+0.278R, DSR=99.9% | E[R] >= +0.05R, t >= 2.6, E[R]×1,5 > 0, DSR >= 95% | **PASS** |
| 3 | Testul cu direcție aleatoare (1.000 rulări) | 100.0% bătute | >= 95% | **PASS** |
| 4 | Consistență pe ani (2018–2026) | 100.0% ani pe plus, cel mai slab an 0.3% | >= 60% ani > 0 și niciun an < -15% | **PASS** |
| 5 | Sharpe anualizat OOS (√252) | 1.75 | >= 1.00 | **PASS** |
| 6 | Stabilitate la ±20% pe parametri | 18/18 cu E[R] > 0 (minim +0.197R) | E[R] > 0 în toate variantele | **PASS** |
| 7 | Bate martorul D2 (ORB 5m) după Sharpe OOS | Sharpe 1.75 vs D2 0.42 | Sharpe > 0.42 | **PASS** |
| 8 | Fereastra nevăzută de autor (D29b: oct. 2024 – oct. 2026) | E[R]=+0.067R | E[R] > 0 | **PASS** |

## 2. Metrici OOS principale (`2018-01-02 → 2026-10-30`, varianta judecată Long-Only)

| Strategie | Tranzacții | Win Rate | Profit Factor | E[R] net | t-stat (p Bonf. ×9) | E[R] cost ×1,5 | CAGR | Sharpe (√252) | Max DD | DSR (N=9) | Capital final (din 500 $) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| D1 (calibrat lunar 24m) | 2046 | 42.6% | 1.26 | +0.0316R | 3.50 (0.002) | +0.0276R | 2.99% | 0.99 | 5.16% | 68.3% | 648.35 $ |
| D1 (default L=14, m=1.0) | 1998 | 44.0% | 1.33 | +0.0323R | 4.12 (0.000) | +0.0285R | 3.23% | 1.18 | 2.86% | 86.3% | 662.00 $ |
| D1b (VWAP & Ladder #1, Maróy 2025) | 1399 | 39.8% | 1.60 | +0.3034R | 5.79 (0.000) | +0.2783R | 4.50% | 1.75 | 1.90% | 99.9% | 737.60 $ |
| D2 (ORB 5m, martor) | 2169 | 24.0% | 1.10 | +0.0882R | 1.71 (0.397) | +0.0613R | 2.19% | 0.42 | 7.89% | 9.1% | 605.52 $ |
| Buy & Hold SPY | — | — | — | — | — | — | 12.43% | 0.71 | 34.23% | — | 1405.67 $ |
| Buy & Hold 50/50 SPY+QQQ | — | — | — | — | — | — | 15.57% | 0.78 | 31.14% | — | 1792.21 $ |

*Notă DSR:* `sr_variance = 0.001202` (`max(1/(T-1), var_empirică)` pe T = 2.221 zile OOS). Riscul mediu pe tranzacție (`avg_risk_pct`) a fost: D1_cal `0.442%`, D1_def `0.454%`, D1b `0.089%`, D2 `0.111%`. Zile cu pierdere sub −2%: D1_cal `0`, D1_def `0`, D1b `0`, D2 `0`.

## 3. Randamente pe ani calendaristici (`2018–2026`, Long-Only)

| Strategie | 2018 | 2019 | 2020 | 2021 | 2022 | 2023 | 2024 | 2025 | 2026 | Ani > 0 | Cel mai slab an |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| D1 (calibrat lunar 24m) | +0.7% | +0.5% | -1.0% | +8.8% | +7.7% | +8.2% | +4.3% | -0.2% | -1.8% | 6/9 (67%) | -1.8% |
| D1 (default L=14, m=1.0) | +2.8% | +2.0% | +0.9% | +6.7% | +4.6% | +6.6% | +4.8% | +1.0% | -0.7% | 8/9 (89%) | -0.7% |
| D1b (VWAP & Ladder #1, Maróy 2025) | +4.3% | +2.0% | +1.8% | +9.8% | +9.1% | +8.4% | +3.8% | +0.3% | +0.7% | 9/9 (100%) | +0.3% |
| D2 (ORB 5m, martor) | -1.2% | +7.0% | -3.0% | +5.0% | +16.1% | -1.5% | +0.3% | -1.5% | -0.5% | 4/9 (44%) | -3.0% |

## 4. Variante informative: Long+Short (expunere 2×) și costuri CFD

### 4.1 Long+Short (`long_only=False, max_exposure=2.0, cost_variant='stock'`)

| Strategie | Tranzacții (Long / Short) | Win Rate | PF | E[R] net | t-stat | CAGR | Sharpe | Max DD | Capital final |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| D1 (calibrat lunar 24m) | 3992 (2046L / 1946S) | 39.8% | 1.23 | +0.0303R | 4.36 | 5.92% | 1.22 | 6.84% | 830.30 $ |
| D1 (default L=14, m=1.0) | 3824 (1998L / 1826S) | 40.8% | 1.27 | +0.0310R | 4.93 | 6.18% | 1.37 | 5.15% | 848.92 $ |
| D1b (VWAP & Ladder #1, Maróy 2025) | 2982 (1399L / 1583S) | 34.0% | 1.37 | +0.2191R | 5.40 | 7.06% | 1.70 | 3.40% | 913.18 $ |
| D2 (ORB 5m, martor) | 4218 (2169L / 2049S) | 22.5% | 1.06 | +0.0672R | 1.74 | 2.64% | 0.37 | 10.93% | 629.15 $ |

### 4.2 Costuri CFD (`long_only=True, cost_variant='cfd'`)

| Strategie | Tranzacții | Win Rate | PF | E[R] net | t-stat | CAGR | Sharpe | Max DD | Capital final |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| D1 (calibrat lunar 24m) | 2046 | 38.3% | 1.02 | +0.0019R | 0.21 | 0.28% | 0.11 | 8.93% | 512.57 $ |
| D1 (default L=14, m=1.0) | 1998 | 39.3% | 1.05 | +0.0034R | 0.44 | 0.50% | 0.20 | 6.27% | 522.62 $ |
| D1b (VWAP & Ladder #1, Maróy 2025) | 1312 | 38.6% | 1.26 | +0.1438R | 2.97 | 2.23% | 0.90 | 4.18% | 607.58 $ |
| D2 (ORB 5m, martor) | 1901 | 24.6% | 0.94 | -0.0833R | -1.60 | -1.31% | -0.21 | 16.26% | 445.27 $ |

## 5. Testul cu direcție aleatoare (1.000 rulări, seed 42, D27)

| Strategie | Variantă | E[R] replay strategie | p5 aleator | p50 aleator | p95 aleator | % rulări bătute | p-value |
|---|---|---:|---:|---:|---:|---:|---:|
| D1 (calibrat lunar 24m) | Long-Only (judecat) | +0.0284R | -0.0205R | -0.0053R | +0.0106R | **100.0%** | 0.0010 |
| D1 (calibrat lunar 24m) | Long+Short (informativ) | +0.0276R | -0.0198R | -0.0051R | +0.0113R | 100.0% | 0.0010 |
| D1 (default L=14, m=1.0) | Long-Only (judecat) | +0.0530R | -0.0057R | +0.0093R | +0.0247R | **100.0%** | 0.0010 |
| D1 (default L=14, m=1.0) | Long+Short (informativ) | +0.0345R | -0.0213R | -0.0063R | +0.0084R | 100.0% | 0.0010 |
| D1b (VWAP & Ladder #1, Maróy 2025) | Long-Only (judecat) | +0.3155R | -0.0098R | +0.0554R | +0.1289R | **100.0%** | 0.0010 |
| D1b (VWAP & Ladder #1, Maróy 2025) | Long+Short (informativ) | +0.2227R | -0.0209R | +0.0307R | +0.0907R | 100.0% | 0.0010 |
| D2 (ORB 5m, martor) | Long-Only (judecat) | +0.1036R | -0.0067R | +0.0614R | +0.1341R | **82.8%** | 0.1728 |
| D2 (ORB 5m, martor) | Long+Short (informativ) | +0.0819R | -0.0235R | +0.0294R | +0.0859R | 94.0% | 0.0609 |

## 6. Stabilitate la ±20% pe parametri (Criteriul 6)

### D1 (calibrat lunar 24m)

| Perturbație parametru | Expectancy E[R] net OOS | Status (> 0) |
|---|---:|---|
| `L-20%` | +0.0301R | **PASS** |
| `L+20%` | +0.0315R | **PASS** |
| `m-20%` | +0.0274R | **PASS** |
| `m+20%` | +0.0359R | **PASS** |

### D1 (default L=14, m=1.0)

| Perturbație parametru | Expectancy E[R] net OOS | Status (> 0) |
|---|---:|---|
| `L-20% (11, 1.0)` | +0.0289R | **PASS** |
| `L+20% (17, 1.0)` | +0.0346R | **PASS** |
| `m-20% (14, 0.8)` | +0.0317R | **PASS** |
| `m+20% (14, 1.2)` | +0.0279R | **PASS** |

### D1b (VWAP & Ladder #1, Maróy 2025)

| Perturbație parametru | Expectancy E[R] net OOS | Status (> 0) |
|---|---:|---|
| `lookback-20%=3` | +0.2982R | **PASS** |
| `lookback+20%=5` | +0.2695R | **PASS** |
| `first_check_min-20%=33` | +0.1971R | **PASS** |
| `first_check_min+20%=49` | +0.2119R | **PASS** |
| `check_freq_min-20%=37` | +0.2045R | **PASS** |
| `check_freq_min+20%=55` | +0.2145R | **PASS** |
| `exit_before_close_min-20%=24` | +0.2649R | **PASS** |
| `exit_before_close_min+20%=36` | +0.2878R | **PASS** |
| `mult-20%=1.064` | +0.2771R | **PASS** |
| `mult+20%=1.596` | +0.3173R | **PASS** |
| `sigma_target-20%=0.02` | +0.3104R | **PASS** |
| `sigma_target+20%=0.03` | +0.3040R | **PASS** |
| `stop_0-20%=-0.328` | +0.3199R | **PASS** |
| `stop_0+20%=-0.492` | +0.2967R | **PASS** |
| `stop_1-20%=-0.224` | +0.3009R | **PASS** |
| `stop_1+20%=-0.336` | +0.3034R | **PASS** |
| `take_profit_0-20%=1.76` | +0.2987R | **PASS** |
| `take_profit_0+20%=2.64` | +0.3028R | **PASS** |

## 7. Fereastra nevăzută de autorul D1b (`2024-10-01 → 2026-10-30`, D29b)

În Maróy (2025), parametrii `VWAP & Ladder #1` au fost optimizați pe QQQ `2014-10-01 → 2024-10-01`. Performanța pur out-of-sample față de fereastra autorului este:

| Strategie | Tranzacții | Win Rate | PF | E[R] net | t-stat | CAGR | Sharpe | Max DD |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| D1 (calibrat lunar 24m) | 494 | 38.1% | 0.97 | -0.0016R | -0.10 | -0.34% | -0.12 | 5.16% |
| D1 (default L=14, m=1.0) | 460 | 42.4% | 1.12 | +0.0120R | 0.77 | 1.12% | 0.46 | 2.86% |
| D1b (VWAP & Ladder #1, Maróy 2025) | 327 | 37.9% | 1.11 | +0.0668R | 0.64 | 0.74% | 0.38 | 1.90% |
| D2 (ORB 5m, martor) | 499 | 24.8% | 0.98 | +0.0007R | 0.01 | -0.33% | -0.06 | 5.41% |

## 8. Verificarea semnalelor IEX cu execuție SIP (`2020-08-03 → 2026-10-30`, D26/D29)

| Strategie | Sursă semnale | Tranzacții | E[R] net | PF | Sharpe | CAGR | Max DD | Raport E[R] IEX / SIP |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| D1 (calibrat lunar 24m) | SIP (referință) | 1608 | +0.0398R | 1.31 | 1.24 | 4.10% | 5.16% | — |
| D1 (calibrat lunar 24m) | IEX (exec. SIP) | 1517 | +0.0365R | 1.28 | 1.10 | 3.56% | 5.35% | **91.6%** |
| D1 (default L=14, m=1.0) | SIP (referință) | 1423 | +0.0375R | 1.36 | 1.30 | 3.65% | 2.86% | — |
| D1 (default L=14, m=1.0) | IEX (exec. SIP) | 1279 | +0.0318R | 1.30 | 1.06 | 2.89% | 3.46% | **84.8%** |
| D1b (VWAP & Ladder #1, Maróy 2025) | SIP (referință) | 1014 | +0.3669R | 1.69 | 1.99 | 5.43% | 1.90% | — |
| D1b (VWAP & Ladder #1, Maróy 2025) | IEX (exec. SIP) | 992 | +0.3360R | 1.72 | 2.00 | 5.33% | 1.80% | **91.6%** |

## 9. Distribuția perechilor `(L, m)` alese în calibrarea lunară D1 (106 luni OOS)

| Pereche `(L, m)` | Luni alese (din 106) | Pondere |
|---|---:|---:|
| `L=7, m=0.75` | 36 | 34.0% |
| `L=14, m=1.5` | 13 | 12.3% |
| `L=14, m=1.0` | 12 | 11.3% |
| `L=20, m=0.75` | 11 | 10.4% |
| `L=28, m=1.5` | 6 | 5.7% |
| `L=7, m=1.0` | 5 | 4.7% |
| `L=7, m=1.25` | 4 | 3.8% |
| `L=10, m=0.75` | 4 | 3.8% |
| `L=28, m=0.75` | 3 | 2.8% |
| `L=7, m=1.5` | 2 | 1.9% |
| `L=20, m=1.0` | 2 | 1.9% |
| `L=20, m=1.5` | 2 | 1.9% |
| `L=28, m=1.0` | 2 | 1.9% |
| `L=10, m=1.5` | 1 | 0.9% |
| `L=14, m=0.75` | 1 | 0.9% |
| `L=20, m=1.25` | 1 | 0.9% |
| `L=28, m=1.25` | 1 | 0.9% |

*Timp total de execuție evaluare Poarta 1 B:* `154.5 s`.
