"""Faza B, B1: validate the cached 1-minute bars and compare SIP vs IEX (offline, after download).

Reads data/cache/minute/, writes .cache/b1_data.json (full) and reports/b1_date.md
(Romanian summary).
Run: PYTHONPATH=. uv run python scripts/b1_data_report.py
"""

import json
from pathlib import Path

from src.data.feed_compare import compare_feeds
from src.data.intraday import load_minute_bars
from src.data.intraday_validation import is_clean, validate_minute_bars

ROOT = Path(__file__).resolve().parent.parent
SYMBOLS = ["SPY", "QQQ"]
FEED_START = {"sip": "2016-01-04", "iex": "2020-07-27"}
JSON_OUT = ROOT / ".cache" / "b1_data.json"
MD_OUT = ROOT / "reports" / "b1_date.md"


def _short_list(items, n=8) -> str:
    items = list(items)
    if not items:
        return "niciuna"
    more = f" (+{len(items) - n})" if len(items) > n else ""
    return ", ".join(items[:n]) + more


def main() -> None:
    data, result = {}, {"validation": {}, "sip_vs_iex": {}}
    for feed, start in FEED_START.items():
        for sym in SYMBOLS:
            df = load_minute_bars(sym, feed)
            data[(feed, sym)] = df
            rep = validate_minute_bars(df, start=start)
            rep["clean"] = is_clean(rep)
            result["validation"][f"{feed}_{sym}"] = rep
    for sym in SYMBOLS:
        result["sip_vs_iex"][sym] = compare_feeds(data[("sip", sym)], data[("iex", sym)])
    JSON_OUT.parent.mkdir(parents=True, exist_ok=True)
    JSON_OUT.write_text(json.dumps(result, indent=2))

    lines = [
        "# Faza B, B1: datele de 1 minut",
        "",
        "Generat de `scripts/b1_data_report.py`. "
        "Detaliile complete: `.cache/b1_data.json` (local).",
        "",
        "## Validare față de calendarul bursei NYSE",
        "",
        "| Set | Zile bursă | Zile cu date | Bare | Zile lipsă "
        "| Sesiuni incomplete (< 95%) | Dubluri |",
        "|---|---|---|---|---|---|---|",
    ]
    for key, rep in result["validation"].items():
        feed, sym = key.split("_")
        lines.append(
            f"| {sym} {feed.upper()} | {rep['sessions']} | {rep['days_with_bars']} "
            f"| {rep['bars']:,} "
            f"| {len(rep['missing_days'])} | {len(rep['short_sessions'])} | {rep['duplicates']} |"
        )
    lines.append("")
    for key, rep in result["validation"].items():
        feed, sym = key.split("_")
        short = [f"{d} ({b}/{e})" for d, (b, e) in rep["short_sessions"].items()]
        lines.append(
            f"- {sym} {feed.upper()}: zile lipsă: {_short_list(rep['missing_days'])}; "
            f"sesiuni incomplete: {_short_list(short)}; zile cu închidere la 13:00: "
            f"{len(rep['early_closes'])}; bare în afara sesiunii: {rep['outside_session']}; "
            f"bare cu prețuri incoerente: {rep['bad_ohlc']}."
        )
    lines += [
        "",
        "## SIP (istoric, backtest) față de IEX (folosit live în demo)",
        "",
        "Diferențe în puncte de bază (1 pb = 0,01%), IEX minus SIP, pe zilele comune.",
        "",
        "| Simbol | Zile | Minute IEX / SIP | Volum IEX / SIP | Închidere: mediană / p95 / max "
        "| VWAP sesiune: mediană / p95 / max | VWAP după 10:00: mediană / p95 / max |",
        "|---|---|---|---|---|---|---|",
    ]
    for sym, c in result["sip_vs_iex"].items():

        def s(k):
            return f"{c[k]['median']} / {c[k]['p95']} / {c[k]['max']}"

        lines.append(
            f"| {sym} | {c['days']} | {c['coverage']:.1%} | {c['volume_share']:.1%} "
            f"| {s('close_bps')} | {s('vwap_bps')} | {s('vwap_bps_after_30min')} |"
        )
    MD_OUT.write_text("\n".join(lines) + "\n")
    print(json.dumps(result["sip_vs_iex"], indent=1))
    for key, rep in result["validation"].items():
        print(
            key,
            "clean" if rep["clean"] else "ISSUES",
            len(rep["missing_days"]),
            len(rep["short_sessions"]),
            rep["duplicates"],
            rep["outside_session"],
            rep["bad_ohlc"],
        )


if __name__ == "__main__":
    main()
