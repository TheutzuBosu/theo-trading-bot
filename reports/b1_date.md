# Faza B, B1: datele de 1 minut

Generat de `scripts/b1_data_report.py`. Detaliile complete: `.cache/b1_data.json` (local).

## Validare față de calendarul bursei NYSE

| Set | Zile bursă | Zile cu date | Bare | Zile lipsă | Sesiuni incomplete (< 95%) | Dubluri |
|---|---|---|---|---|---|---|
| SPY SIP | 2724 | 2724 | 1,058,476 | 0 | 1 | 0 |
| QQQ SIP | 2724 | 2724 | 1,058,465 | 0 | 1 | 0 |
| SPY IEX | 1576 | 1575 | 601,542 | 1 | 161 | 0 |
| QQQ IEX | 1576 | 1575 | 563,467 | 1 | 768 | 0 |

- SPY SIP: zile lipsă: niciuna; sesiuni incomplete: 2019-08-12 (360/390); zile cu închidere la 13:00: 21; bare în afara sesiunii: 0; bare cu prețuri incoerente: 0.
- QQQ SIP: zile lipsă: niciuna; sesiuni incomplete: 2016-02-22 (340/390); zile cu închidere la 13:00: 21; bare în afara sesiunii: 0; bare cu prețuri incoerente: 0.
- SPY IEX: zile lipsă: 2025-03-10; sesiuni incomplete: 2020-07-29 (359/390), 2020-07-30 (368/390), 2020-08-05 (356/390), 2020-08-06 (358/390), 2020-08-07 (370/390), 2020-08-10 (370/390), 2020-08-11 (368/390), 2020-08-12 (364/390) (+153); zile cu închidere la 13:00: 12; bare în afara sesiunii: 0; bare cu prețuri incoerente: 0.
- QQQ IEX: zile lipsă: 2025-03-10; sesiuni incomplete: 2020-07-27 (318/390), 2020-07-28 (295/390), 2020-07-29 (278/390), 2020-07-30 (354/390), 2020-07-31 (325/390), 2020-08-03 (321/390), 2020-08-04 (322/390), 2020-08-05 (291/390) (+760); zile cu închidere la 13:00: 12; bare în afara sesiunii: 0; bare cu prețuri incoerente: 0.

## SIP (istoric, backtest) față de IEX (folosit live în demo)

Diferențe în puncte de bază (1 pb = 0,01%), IEX minus SIP, pe zilele comune.

| Simbol | Zile | Minute IEX / SIP | Volum IEX / SIP | Închidere: mediană / p95 / max | VWAP sesiune: mediană / p95 / max | VWAP după 10:00: mediană / p95 / max |
|---|---|---|---|---|---|---|
| SPY | 1575 | 98.3% | 2.0% | 0.365 / 2.266 / 33.365 | 1.241 / 6.888 / 79.427 | 1.273 / 7.107 / 79.427 |
| QQQ | 1575 | 92.1% | 1.4% | 0.692 / 4.069 / 40.879 | 2.311 / 11.778 / 145.68 | 2.377 / 12.081 / 145.68 |
