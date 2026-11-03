"""Gate 1 (docs/PLAN.md, etapa 3b): walk-forward, Monte Carlo, random-entry test and the +/-20%
parameter test for S1-S4, in two variants: fractional and whole shares (D15).

Run once (~20 min, data from scripts/download_history.py):
    PYTHONPATH=. uv run python scripts/gate1.py
Full results go to .cache/gate1/; reports/gate1.md, reports/gate1_results.json and the equity
charts are generated from them. `--report-only` rewrites the report from .cache/gate1/.
"""

from __future__ import annotations

import datetime as dt
import json
import sys
import time
from dataclasses import asdict, replace

import matplotlib
import numpy as np
import pandas as pd

from src.backtest.engine import BacktestConfig, run_backtest
from src.backtest.gate1 import (
    MAX_MC_DRAWDOWN_P95,
    MIN_RANDOM_BEAT,
    MIN_VARIED_PROFIT_FACTOR,
    PARAM_STEP,
    RANDOM_METRIC,
    evaluate,
    passes,
    position_months,
    vary_params,
)
from src.backtest.metrics import benchmark_summary, buy_and_hold
from src.backtest.robustness import monte_carlo, random_entry_test
from src.backtest.sizing import (
    DEFAULT_RISK_PER_TRADE,
    MAX_OPEN_POSITIONS,
    MAX_PER_SECTOR,
    MAX_POSITION_NOTIONAL,
)
from src.backtest.walkforward import build_panels, walk_forward
from src.config import BASE_DIR, settings
from src.data import BENCHMARK_SYMBOL, load_daily, load_universe
from src.strategies import load_strategy

START = "2006-01-01"
STRATEGIES = ("S1", "S2", "S3", "S4")
VARIANTS = {"fractionare": False, "actiuni_intregi": True}  # name -> whole_shares
VARIANT_TITLES = {"fractionare": "Acțiuni fracționare", "actiuni_intregi": "Acțiuni întregi"}
N_RANDOM = 500
N_MONTE_CARLO = 1000
SEED = 42
CACHE = BASE_DIR / ".cache" / "gate1"
REPORTS = BASE_DIR / "reports"


def _clean(obj):
    """JSON-safe copy: NaN/inf -> None, numpy and pandas scalars -> Python."""
    if isinstance(obj, dict):
        return {str(k): _clean(v) for k, v in obj.items()}
    if isinstance(obj, list | tuple):
        return [_clean(v) for v in obj]
    if isinstance(obj, pd.Timestamp | dt.date):
        return obj.strftime("%Y-%m-%d")
    if isinstance(obj, np.bool_ | bool):
        return bool(obj)
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, np.floating | float):
        return float(obj) if np.isfinite(obj) else None
    return obj


def load_market() -> tuple[dict[str, pd.DataFrame], dict[str, str]]:
    universe = load_universe()
    prices = load_daily(universe["symbol"].tolist(), start=START)
    missing = [s for s, df in prices.items() if df.empty]
    if missing:
        raise SystemExit(f"No data for {missing}: run scripts/download_history.py first")
    return prices, dict(zip(universe["symbol"], universe["sector"]))


def evaluate_strategy(name, prices, sectors, whole_shares, capital) -> tuple[dict, pd.Series]:
    spec = load_strategy(name)
    config = BacktestConfig(
        initial_capital=capital, max_hold_bars=spec.max_hold_bars, whole_shares=whole_shares
    )
    wf = walk_forward(spec.signals, prices, config, sectors)
    start, end = wf.equity.index[0], wf.equity.index[-1]
    spy = benchmark_summary(prices[BENCHMARK_SYMBOL], capital, config.costs, start, end)

    mc = monte_carlo(wf.trades, N_MONTE_CARLO, SEED).summary() if len(wf.trades) else {}
    panel, signals = build_panels(spec.signals, prices)
    rnd = random_entry_test(panel, signals, config, sectors, N_RANDOM, SEED, start, end)
    single = run_backtest(panel, signals, config, sectors, start, end)

    varied = []
    for key, value in vary_params(spec.params.model_dump()):
        vspec = load_strategy(name, overrides={key: value})
        vconfig = replace(config, max_hold_bars=vspec.max_hold_bars)
        vwf = walk_forward(vspec.signals, prices, vconfig, sectors, check_lookahead=False)
        varied.append(
            {
                "param": key,
                "base": getattr(spec.params, key),
                "value": value,
                "profit_factor": vwf.summary["profit_factor"],
                "n_trades": vwf.summary["n_trades"],
                "sharpe": vwf.summary["sharpe"],
            }
        )

    months = position_months(wf.trades) if len(wf.trades) else 0
    criteria = evaluate(
        name,
        wf.summary,
        spy,
        months,
        [v["profit_factor"] for v in varied],
        rnd.beats[RANDOM_METRIC],
        mc.get("drawdown_p95", np.nan),
    )
    result = {
        "name": name,
        "title": spec.title,
        "params": spec.params.model_dump(),
        "oos_start": start,
        "oos_end": end,
        "oos": wf.summary,
        "spy": spy,
        "position_months": months,
        "windows": wf.windows.to_dict(orient="records"),
        "exit_reasons": wf.trades["exit_reason"].value_counts().to_dict() if len(wf.trades) else {},
        "monte_carlo": mc,
        "random": {
            "strategy": rnd.strategy,
            "beats": rnd.beats,
            "random_median": rnd.random.median().to_dict(),
            "random_p95": rnd.random.quantile(0.95).to_dict(),
        },
        "rejections": single.rejections["reason"].value_counts().to_dict(),
        "varied": varied,
        "criteria": [asdict(c) for c in criteria],
        "passed": passes(criteria),
    }
    return result, wf.equity


def run_all() -> None:
    CACHE.mkdir(parents=True, exist_ok=True)
    prices, sectors = load_market()
    capital = settings.BOT_CAPITAL
    stocks = {s: df for s, df in prices.items() if s != BENCHMARK_SYMBOL}
    last_close = pd.Series({s: float(df["close"].iloc[-1]) for s, df in stocks.items()})
    spy_df = prices[BENCHMARK_SYMBOL]
    meta = {
        "run_date": dt.date.today(),
        "capital": capital,
        "data_start": spy_df.index[0],
        "data_end": spy_df.index[-1],
        "n_stocks": len(stocks),
        "late_starts": {
            s: df.index[0] for s, df in stocks.items() if df.index[0] > spy_df.index[0]
        },
        "affordable_today": int((last_close <= MAX_POSITION_NOTIONAL * capital).sum()),
        "max_notional": MAX_POSITION_NOTIONAL * capital,
    }
    results = {}
    for variant, whole in VARIANTS.items():
        results[variant] = {}
        curves = {}
        for name in STRATEGIES:
            t0 = time.time()
            res, equity = evaluate_strategy(name, prices, sectors, whole, capital)
            results[variant][name] = res
            curves[name] = equity
            verdict = "PASS" if res["passed"] else "FAIL"
            print(f"{variant} {name}: {verdict} ({time.time() - t0:.0f}s)", flush=True)
        start, end = curves[STRATEGIES[0]].index[[0, -1]]
        curves["SPY"] = buy_and_hold(spy_df, capital, start=start, end=end)
        pd.DataFrame(curves).to_csv(CACHE / f"equity_{variant}.csv")
    with open(CACHE / "results.json", "w", encoding="utf-8") as fh:
        json.dump(_clean({"meta": meta, "results": results}), fh, indent=1, ensure_ascii=False)


# --- report -------------------------------------------------------------------------------


def pct(x, signed=False) -> str:
    if x is None:
        return "n/a"
    return f"{x:+.1%}" if signed else f"{x:.1%}"


def num(x, fmt=".2f") -> str:
    return "n/a" if x is None else format(x, fmt)


def plot_equity(variant: str) -> str:
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    curves = pd.read_csv(CACHE / f"equity_{variant}.csv", index_col=0, parse_dates=True)
    fig, ax = plt.subplots(figsize=(10, 5.5))
    for col in curves.columns:
        style = {"color": "black", "linewidth": 2.2} if col == "SPY" else {"linewidth": 1.3}
        label = "SPY (cumpărat și ținut)" if col == "SPY" else col
        ax.plot(curves.index, curves[col], label=label, **style)
    ax.set_yscale("log")
    ax.set_title(f"Poarta 1, out-of-sample: 500 $ investiți ({VARIANT_TITLES[variant].lower()})")
    ax.set_ylabel("Valoarea contului ($, scară logaritmică)")
    ax.grid(True, which="both", alpha=0.3)
    ax.legend(loc="upper left")
    fig.tight_layout()
    name = f"gate1_equity_{variant}.png"
    fig.savefig(REPORTS / name, dpi=110)
    plt.close(fig)
    return name


def worst_varied_pf(r: dict):
    """Lowest PF among the +/-20% variants; None (no trades) counts as the worst."""
    pfs = [v["profit_factor"] for v in r["varied"]]
    return None if not pfs or None in pfs else min(pfs)


def summary_table(res: dict) -> list[str]:
    spy = res[STRATEGIES[0]]["spy"]
    rows = [
        ("Tranzacții OOS", lambda r: f"{r['oos']['n_trades']}", "1"),
        (
            "Randament total",
            lambda r: pct(r["oos"]["total_return"], True),
            pct(spy["total_return"], True),
        ),
        ("CAGR (pe an)", lambda r: pct(r["oos"]["cagr"], True), pct(spy["cagr"], True)),
        ("Sharpe", lambda r: num(r["oos"]["sharpe"]), num(spy["sharpe"])),
        ("Drawdown maxim", lambda r: pct(r["oos"]["max_drawdown"]), pct(spy["max_drawdown"])),
        ("Profit factor", lambda r: num(r["oos"]["profit_factor"]), "-"),
        ("Expectancy (R)", lambda r: num(r["oos"]["expectancy_r"], "+.2f"), "-"),
        ("Tranzacții câștigătoare", lambda r: pct(r["oos"]["win_rate"]), "-"),
        ("Expunere medie", lambda r: pct(r["oos"]["avg_exposure"]), "100%"),
        ("Ferestre profitabile", lambda r: pct(r["oos"]["windows_profitable_pct"]), "-"),
        ("MC drawdown p95", lambda r: pct(r["monte_carlo"].get("drawdown_p95")), "-"),
        ("Bate intrările aleatoare", lambda r: pct(r["random"]["beats"][RANDOM_METRIC]), "-"),
        (f"PF minim la ±{PARAM_STEP:.0%}", lambda r: num(worst_varied_pf(r)), "-"),
        ("**Verdict**", lambda r: "**PASS**" if r["passed"] else "**FAIL**", "-"),
    ]
    lines = ["| | " + " | ".join(STRATEGIES) + " | SPY |", "|---" * (len(STRATEGIES) + 2) + "|"]
    for label, cell, spy_cell in rows:
        lines.append(
            f"| {label} | " + " | ".join(cell(res[s]) for s in STRATEGIES) + f" | {spy_cell} |"
        )
    return lines


def criteria_table(res: dict) -> list[str]:
    lines = [
        "| # | Criteriu | " + " | ".join(STRATEGIES) + " |",
        "|---" * (len(STRATEGIES) + 2) + "|",
    ]
    for i, crit in enumerate(res[STRATEGIES[0]]["criteria"]):
        cells = []
        for s in STRATEGIES:
            c = res[s]["criteria"][i]
            cells.append(("✅ " if c["passed"] else "❌ ") + c["value"])
        lines.append(
            f"| {crit['number']} | {crit['name']} ({crit['threshold']}) | "
            + " | ".join(cells)
            + " |"
        )
    return lines


def varied_table(res: dict) -> list[str]:
    lines = [
        "| Strategie | Parametru | Bază | Variantă | PF | Tranzacții | Sharpe |",
        "|---|---|---|---|---|---|---|",
    ]
    for s in STRATEGIES:
        for v in res[s]["varied"]:
            pf = v["profit_factor"]
            mark = "" if pf is not None and pf > MIN_VARIED_PROFIT_FACTOR else " ❌"
            lines.append(
                f"| {s} | {v['param']} | {v['base']:g} | {v['value']:g} | {num(pf)}{mark} "
                f"| {v['n_trades']} | {num(v['sharpe'])} |"
            )
    return lines


def write_report() -> None:
    with open(CACHE / "results.json", encoding="utf-8") as fh:
        data = json.load(fh)
    meta, results = data["meta"], data["results"]
    first = results["fractionare"][STRATEGIES[0]]
    n_windows = first["oos"]["n_windows"]
    passed = {v: [s for s in STRATEGIES if results[v][s]["passed"]] for v in VARIANTS}

    out = [
        "# Poarta 1: rezultatul backtestului",
        "",
        f"{meta['run_date']} · Claude Code · etapa 3b · generat de `scripts/gate1.py`",
        "",
        "## Pe scurt",
        "",
    ]
    if not any(passed.values()):
        out += [
            "**Nicio strategie nu trece Poarta 1, în niciuna dintre variante.** "
            "Conform planului (D7), nu trecem la bani, nici la paper trading cu aceste strategii.",
            "",
        ]
    for v in VARIANTS:
        for s in STRATEGIES:
            r = results[v][s]
            bad = [str(c["number"]) for c in r["criteria"] if not c["passed"]]
            verdict = "PASS" if r["passed"] else f"FAIL (criteriile {', '.join(bad)})"
            out.append(f"- {VARIANT_TITLES[v]}, {r['title']}: **{verdict}**")
    out += [
        "",
        "## Cum s-a testat",
        "",
        f"- Date: {meta['n_stocks']} acțiuni din `config/universe.csv` (S&P 100) și SPY, "
        f"zilnic, {meta['data_start']} – {meta['data_end']}, prețuri ajustate cu dividende "
        "și split-uri (yfinance).",
        "- Out-of-sample (OOS): walk-forward cu 3 ani de istoric înaintea fiecărei ferestre "
        f"de test de 1 an; OOS = {first['oos_start']} – {first['oos_end']} ({n_windows} "
        "ferestre). Fiecare fereastră pornește cu capitalul inițial; curba OOS înlănțuie "
        "ferestrele (D10).",
        "- Parametrii sunt cei din `config/strategies.yaml`, aceiași în toate ferestrele, "
        "neoptimizați.",
        "- Costuri pe fiecare parte: slippage 0.10% + jumătate de spread 0.05%; comision 0.",
        f"- Capital {meta['capital']:.0f} $; risc {DEFAULT_RISK_PER_TRADE:.1%} din cont pe "
        f"tranzacție; maximum {MAX_POSITION_NOTIONAL:.0%} din cont pe o poziție, "
        f"{MAX_OPEN_POSITIONS} poziții, {MAX_PER_SECTOR} pe sector; fără levier.",
        "- SPY: cumpărat la începutul perioadei OOS și ținut până la final, cu aceleași costuri.",
        f"- Monte Carlo: {N_MONTE_CARLO} de reamestecări ale ordinii tranzacțiilor OOS. "
        f"Intrări aleatoare: {N_RANDOM} de rulări pe perioada OOS (aceleași ieșiri, stopuri "
        f"și sizing), comparate după Sharpe. Testul ±{PARAM_STEP:.0%}: fiecare parametru pe "
        "rând, restul la bază (D17).",
        "",
    ]
    for v in VARIANTS:
        res = results[v]
        out += [f"## Rezultate: {VARIANT_TITLES[v].lower()}", ""]
        out += summary_table(res)
        out += ["", f"![Equity OOS vs SPY, {VARIANT_TITLES[v].lower()}]({plot_equity(v)})", ""]
        out += ["Criteriile, pe rând:", ""]
        out += criteria_table(res)
        out += [""]
        if v == "actiuni_intregi":
            rej = {s: res[s]["rejections"].get("qty_too_small", 0) for s in STRATEGIES}
            out += [
                "Intrări respinse pentru că nici o acțiune întreagă nu încăpea în risc sau în "
                "plafonul de poziție (backtest continuu pe perioada OOS): "
                + ", ".join(f"{s} {n}" for s, n in rej.items())
                + ".",
                "",
            ]
    out += [f"## Testul ±{PARAM_STEP:.0%} în detaliu", ""]
    for v in VARIANTS:
        out += [f"<details><summary>{VARIANT_TITLES[v]}</summary>", ""]
        out += varied_table(results[v])
        out += ["", "</details>", ""]
    late = ", ".join(f"{s} ({d[:4]})" for s, d in meta["late_starts"].items())
    cap, max_pos = meta["capital"], meta["max_notional"]
    out += [
        "## Note și limite",
        "",
        "- **Survivorship bias.** Universul este lista S&P 100 de azi, aplicată pe tot "
        "istoricul. Firmele care au ieșit din indice sau au dat faliment lipsesc, iar cele "
        "ajunse azi în S&P 100 (deci câștigătoarele) sunt incluse din 2006. Rezultatele "
        "strategiilor sunt astfel mai bune decât ar fi fost în realitate, mai ales la momentum "
        "și breakout. Un FAIL e sigur; un PASS ar trebui privit cu prudență.",
        f"- Acțiuni listate după începutul datelor: {late}. Ele apar doar de la listare.",
        "- **Sharpe nu depinde de cât din cont e investit** (rata fără risc 0), deci "
        "comparația cu SPY e corectă chiar dacă strategiile stau mult în cash. CAGR-ul mic "
        "vine și din riscul de 0.5% pe tranzacție.",
        "- **Acțiuni întregi:** prețurile istorice sunt ajustate pentru split-uri, deci în "
        "trecut acțiunile par mai ieftine decât au fost (de exemplu AAPL), iar varianta e "
        f"optimistă. Azi, la {cap:.0f} $ cu maximum {max_pos:.0f} $ pe poziție, doar "
        f"{meta['affordable_today']} din {meta['n_stocks']} acțiuni costă cel mult "
        f"{max_pos:.0f} $.",
        f"- OOS începe în {first['oos_start'][:4]}: criza din 2008 e doar în istoricul primei "
        "ferestre, nu în OOS.",
        "- S2: criteriul 1 numără poziții-lună (o poziție ținută peste un sfârșit de lună = 1, "
        "minimum 1).",
        f"- Criteriul 6 cere Sharpe-ul strategiei peste {MIN_RANDOM_BEAT:.0%} din rulările "
        f"aleatoare; criteriul 7 cere drawdown-ul p95 sub {MAX_MC_DRAWDOWN_P95:.0%}. Regulile "
        "de evaluare au fost fixate înaintea rulării complete (D17).",
        "",
        "## Ce urmează",
        "",
    ]
    if not any(passed.values()):
        out += [
            "Planul spune: dacă nicio strategie nu trece, ne oprim. Parametrii **nu** se "
            "ajustează ca să treacă (interdicția 6). Decizia e a proprietarului: fie oprim "
            "proiectul aici (D7), fie aprobă o iterație documentată (maximum 2 per strategie), "
            "cu motivul scris în `docs/DECISIONS.md` înainte de rulare, nu după ce vedem "
            "rezultatele.",
        ]
    else:
        out += [
            "Strategiile care trec merg mai departe la etapa 4 (risk guard), apoi la paper "
            "trading (Poarta 2). Cele care nu trec se abandonează.",
        ]
    (REPORTS / "gate1.md").write_text("\n".join(out) + "\n", encoding="utf-8")

    compact = {
        "meta": meta,
        "results": {
            v: {
                s: {
                    k: r[k]
                    for k in ("title", "oos_start", "oos_end", "oos", "spy", "criteria", "passed")
                }
                for s, r in results[v].items()
            }
            for v in VARIANTS
        },
    }
    with open(REPORTS / "gate1_results.json", "w", encoding="utf-8") as fh:
        json.dump(compact, fh, indent=1, ensure_ascii=False)


def main() -> int:
    REPORTS.mkdir(exist_ok=True)
    if "--report-only" not in sys.argv:
        run_all()
    write_report()
    print(f"Report: {REPORTS / 'gate1.md'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
