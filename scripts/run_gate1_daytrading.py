"""Run Poarta 1 B evaluation (D29, D29b) and generate reports/gate1_daytrading.md."""

from __future__ import annotations

import sys
import time
from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.backtest.gate1_daytrading import (
    D1_DEFAULT_PAIR,
    D1_L_GRID,
    D1_M_GRID,
    D1B_UNSEEN_START,
    IEX_START,
    N_TRIALS,
    OOS_END,
    OOS_START,
    calibrate_d1_monthly,
    evaluate_gate1_daytrading,
    passes,
    perturb_d1_pair,
    perturb_d1b_params,
)
from src.backtest.intraday_engine import (
    IntradayConfig,
    IntradayPanel,
    IntradayResult,
    IntradaySignals,
    run_intraday,
)
from src.backtest.intraday_metrics import (
    deflated_sharpe,
    direction_outcomes,
    random_direction_test,
    summarize_intraday,
    yearly_returns,
)
from src.backtest.metrics import daily_returns, equity_metrics
from src.data.intraday import load_minute_bars as load_cached_minute_bars
from src.strategies.intraday_d1 import (
    D1bParams,
    D1Params,
    generate_d1_signals,
    generate_d1b_signals,
)
from src.strategies.intraday_d2 import D2Params, generate_d2_signals

SYMBOLS = ("SPY", "QQQ")
INITIAL_CAPITAL = 500.0


def _slice_by_date(df: pd.DataFrame, start: str, end: str) -> pd.DataFrame:
    ny_dates = df.index.tz_convert("America/New_York").date
    s = pd.Timestamp(start).date()
    e = pd.Timestamp(end).date()
    mask = (ny_dates >= s) & (ny_dates <= e)
    return df.loc[mask]


def _trade_session_dates(trades: pd.DataFrame, panel: IntradayPanel) -> pd.Series:
    if trades.empty:
        return pd.Series([], dtype=object)
    s_idx = np.searchsorted(panel.bounds[:, 0], trades["entry_bar"].to_numpy(), "right") - 1
    return pd.Series(panel.sessions[s_idx].date, index=trades.index)


def _stitch_monthly_signals(
    full_df: pd.DataFrame,
    schedule: list[tuple[str, int, float]],
    sig_cache: dict[tuple[str, int, float], pd.DataFrame],
    symbol: str,
) -> pd.DataFrame:
    """Assemble a full-index signal DataFrame by picking each OOS month's (L, m) signals."""
    ny_periods = full_df.index.tz_convert("America/New_York").tz_localize(None).to_period("M")
    base_sig = sig_cache[(symbol, D1_DEFAULT_PAIR[0], D1_DEFAULT_PAIR[1])]
    out = base_sig.copy()

    for month_str, L, m in schedule:
        key = (symbol, L, m)
        if key not in sig_cache:
            sig_cache[key] = generate_d1_signals(full_df, D1Params(lookback=L, mult=m))
        sig_m = sig_cache[key]
        m_mask = ny_periods == pd.Period(month_str, freq="M")
        if not np.any(m_mask):
            continue
        out.loc[m_mask] = sig_m.loc[m_mask]
    return out


def _buy_and_hold_metrics(
    bars_full: dict[str, pd.DataFrame],
    start: str = OOS_START,
    end: str = OOS_END,
    initial_capital: float = INITIAL_CAPITAL,
) -> dict[str, dict[str, float]]:
    """Compute SPY and 50/50 SPY+QQQ daily Buy & Hold equity metrics on [start, end]."""
    daily_close: dict[str, pd.Series] = {}
    for sym, df in bars_full.items():
        sub = _slice_by_date(df, start, end)
        ny_idx = sub.index.tz_convert("America/New_York").tz_localize(None)
        dates = pd.DatetimeIndex(ny_idx.normalize())
        daily_close[sym] = sub["close"].groupby(dates).last()

    spy_c = daily_close["SPY"]
    qqq_c = daily_close["QQQ"].reindex(spy_c.index).ffill()
    spy_eq = initial_capital * (spy_c / float(spy_c.iloc[0]))
    half_eq = (
        0.5 * initial_capital * ((spy_c / float(spy_c.iloc[0])) + (qqq_c / float(qqq_c.iloc[0])))
    )
    return {
        "SPY": equity_metrics(spy_eq, initial_capital),
        "50/50 SPY+QQQ": equity_metrics(half_eq, initial_capital),
    }


def _cfg_for(name: str, base_cfg: IntradayConfig) -> IntradayConfig:
    """Apply strategy-specific engine settings (D1b uses target_fraction=0.5 per D29b)."""
    if name == "D1b":
        return replace(base_cfg, target_fraction=0.5)
    return base_cfg


def main() -> None:
    t0 = time.perf_counter()
    print("1. Loading SIP 1-minute bars (2016-01-04 .. 2026-10-30)...")
    bars_full = {
        s: _slice_by_date(load_cached_minute_bars(s, "sip"), "2016-01-04", OOS_END) for s in SYMBOLS
    }
    panel_full = IntradayPanel.from_frames(bars_full)
    s0_oos, s1_oos = panel_full.session_range(OOS_START, OOS_END)
    print(
        f"   Built panel_full in {time.perf_counter() - t0:.1f}s: "
        f"total={len(panel_full.sessions)} sessions, OOS={s1_oos - s0_oos + 1} sessions."
    )

    cfg_judged = IntradayConfig(
        initial_capital=INITIAL_CAPITAL,
        cost_variant="stock",
        cost_stress=1.0,
        long_only=True,
        max_exposure=1.0,
        risk_per_trade=0.005,
        max_risk_per_trade=0.005,
        target_fraction=1.0,
        fomc_veto=True,
        whole_shares=False,
        record_rejections=False,
    )
    cfg_stress = replace(cfg_judged, cost_stress=1.5)
    cfg_ls = replace(cfg_judged, long_only=False, max_exposure=2.0)
    cfg_cfd_lo = replace(cfg_judged, cost_variant="cfd")

    # 2. Run the 20 (L, m) grid pairs on full history for D1 monthly calibration
    print("2. Running 20 (L, m) grid pairs for D1 monthly walk-forward calibration...")
    sig_cache: dict[tuple[str, int, float], pd.DataFrame] = {}
    daily_rets_by_pair: dict[tuple[int, float], pd.Series] = {}
    trade_dates_by_pair: dict[tuple[int, float], pd.Series] = {}

    for L in D1_L_GRID:
        for m in D1_M_GRID:
            pair_frames = {}
            for s in SYMBOLS:
                sig = generate_d1_signals(bars_full[s], D1Params(lookback=L, mult=m))
                sig_cache[(s, L, m)] = sig
                pair_frames[s] = sig
            sig_obj = IntradaySignals.from_frames(pair_frames, panel_full)
            res_pair = run_intraday(panel_full, sig_obj, cfg_judged)
            rets = daily_returns(res_pair.equity, INITIAL_CAPITAL)
            rets.index = rets.index.date
            daily_rets_by_pair[(L, m)] = rets
            trade_dates_by_pair[(L, m)] = _trade_session_dates(res_pair.trades, panel_full)

    oos_months = list(pd.period_range("2018-01", "2026-10", freq="M"))
    cal_records = calibrate_d1_monthly(
        daily_rets_by_pair=daily_rets_by_pair,
        trade_dates_by_pair=trade_dates_by_pair,
        oos_months=oos_months,
    )
    base_schedule = [(r.month, r.lookback_days, r.band_mult) for r in cal_records]
    print(f"   Calibrated {len(cal_records)} OOS months ({time.perf_counter() - t0:.1f}s elapsed).")

    # 3. Assemble full signal objects for D1_cal, D1_def, D1b, D2
    print("3. Generating signals for D1_cal, D1_def, D1b, D2...")
    sig_frames: dict[str, dict[str, pd.DataFrame]] = {
        "D1_cal": {
            s: _stitch_monthly_signals(bars_full[s], base_schedule, sig_cache, s) for s in SYMBOLS
        },
        "D1_def": {s: sig_cache[(s, D1_DEFAULT_PAIR[0], D1_DEFAULT_PAIR[1])] for s in SYMBOLS},
        "D1b": {s: generate_d1b_signals(bars_full[s], D1bParams()) for s in SYMBOLS},
        "D2": {s: generate_d2_signals(bars_full[s], D2Params()) for s in SYMBOLS},
    }
    sig_objs = {
        name: IntradaySignals.from_frames(frames, panel_full) for name, frames in sig_frames.items()
    }

    # 4. Run OOS backtests across configurations
    print("4. Running OOS backtests (judged, stress 1.5x, long+short, CFD)...")
    res_judged: dict[str, IntradayResult] = {}
    res_stress: dict[str, IntradayResult] = {}
    res_ls: dict[str, IntradayResult] = {}
    res_cfd: dict[str, IntradayResult] = {}
    metrics_judged: dict[str, dict] = {}
    metrics_ls: dict[str, dict] = {}
    metrics_cfd: dict[str, dict] = {}
    years_judged: dict[str, pd.Series] = {}

    for name, sig_obj in sig_objs.items():
        res_judged[name] = run_intraday(
            panel_full, sig_obj, _cfg_for(name, cfg_judged), start=OOS_START, end=OOS_END
        )
        res_stress[name] = run_intraday(
            panel_full, sig_obj, _cfg_for(name, cfg_stress), start=OOS_START, end=OOS_END
        )
        res_ls[name] = run_intraday(
            panel_full, sig_obj, _cfg_for(name, cfg_ls), start=OOS_START, end=OOS_END
        )
        res_cfd[name] = run_intraday(
            panel_full, sig_obj, _cfg_for(name, cfg_cfd_lo), start=OOS_START, end=OOS_END
        )

        metrics_judged[name] = summarize_intraday(res_judged[name], n_tests=N_TRIALS)
        metrics_ls[name] = summarize_intraday(res_ls[name], n_tests=N_TRIALS)
        metrics_cfd[name] = summarize_intraday(res_cfd[name], n_tests=N_TRIALS)
        years_judged[name] = yearly_returns(res_judged[name].equity, INITIAL_CAPITAL)

    # DSR with sr_variance = max(1/(T-1), empirical variance of daily Sharpes across OOS runs)
    daily_rets_oos = {
        name: daily_returns(res_judged[name].equity, INITIAL_CAPITAL) for name in sig_objs
    }
    sr_periods = [
        float(r.mean() / r.std(ddof=1)) for r in daily_rets_oos.values() if r.std(ddof=1) > 0
    ]
    t_days = len(daily_rets_oos["D1_cal"])
    emp_sr_var = float(np.var(sr_periods, ddof=1)) if len(sr_periods) > 1 else 0.0
    sr_var_used = max(1.0 / (t_days - 1), emp_sr_var)
    dsr_by_name = {
        name: deflated_sharpe(daily_rets_oos[name], n_trials=N_TRIALS, sr_variance=sr_var_used)
        for name in sig_objs
    }

    # 5. Random-direction test (1000 runs, seed 42)
    print("5. Running random-direction tests (1000 runs, seed 42)...")
    rd_lo_summary: dict[str, dict] = {}
    rd_ls_summary: dict[str, dict] = {}
    for name in sig_objs:
        out_ls = direction_outcomes(res_ls[name].trades, panel_full, _cfg_for(name, cfg_ls))
        out_lo = direction_outcomes(res_judged[name].trades, panel_full, _cfg_for(name, cfg_judged))
        actual_lo = float(out_lo["r_own"].mean())
        rd_lo = random_direction_test(
            out_ls, actual=actual_lo, n_runs=1000, seed=42, long_only=True
        )
        rd_ls = random_direction_test(out_ls, n_runs=1000, seed=42, long_only=False)
        rd_lo_summary[name] = rd_lo.summary()
        rd_ls_summary[name] = rd_ls.summary()

    # 6. +/-20% Parameter stability
    print("6. Running +/-20% parameter stability checks...")
    varied_exp: dict[str, dict[str, float]] = {"D1_cal": {}, "D1_def": {}, "D1b": {}}

    # D1_cal: perturb each month's (L, m)
    for tag in ("L-20%", "L+20%", "m-20%", "m+20%"):
        pert_sched = []
        for r in cal_records:
            p_L, p_m = perturb_d1_pair(r.lookback_days, r.band_mult)[tag]
            pert_sched.append((r.month, p_L, p_m))
        pert_frames = {
            s: _stitch_monthly_signals(bars_full[s], pert_sched, sig_cache, s) for s in SYMBOLS
        }
        r_pert = run_intraday(
            panel_full,
            IntradaySignals.from_frames(pert_frames, panel_full),
            cfg_judged,
            start=OOS_START,
            end=OOS_END,
        )
        varied_exp["D1_cal"][tag] = float(r_pert.trades["r_multiple"].mean())

    # D1_def: perturb (14, 1.0)
    for tag, (p_L, p_m) in perturb_d1_pair(*D1_DEFAULT_PAIR).items():
        pert_frames = {}
        for s in SYMBOLS:
            if (s, p_L, p_m) not in sig_cache:
                sig_cache[(s, p_L, p_m)] = generate_d1_signals(
                    bars_full[s], D1Params(lookback=p_L, mult=p_m)
                )
            pert_frames[s] = sig_cache[(s, p_L, p_m)]
        r_pert = run_intraday(
            panel_full,
            IntradaySignals.from_frames(pert_frames, panel_full),
            cfg_judged,
            start=OOS_START,
            end=OOS_END,
        )
        varied_exp["D1_def"][f"{tag} ({p_L}, {p_m})"] = float(r_pert.trades["r_multiple"].mean())

    # D1b: 18 perturbations
    cfg_d1b = _cfg_for("D1b", cfg_judged)
    for label, p_params in perturb_d1b_params(D1bParams()):
        pert_frames = {s: generate_d1b_signals(bars_full[s], p_params) for s in SYMBOLS}
        r_pert = run_intraday(
            panel_full,
            IntradaySignals.from_frames(pert_frames, panel_full),
            cfg_d1b,
            start=OOS_START,
            end=OOS_END,
        )
        varied_exp["D1b"][label] = float(r_pert.trades["r_multiple"].mean())

    # 7. Unseen window (2024-10-01 .. 2026-10-30) for D1b (and comparison for D1_cal, D1_def, D2)
    print("7. Evaluating unseen window (2024-10-01 .. 2026-10-30)...")
    unseen_metrics: dict[str, dict] = {}
    for name, sig_obj in sig_objs.items():
        r_u = run_intraday(
            panel_full,
            sig_obj,
            _cfg_for(name, cfg_judged),
            start=D1B_UNSEEN_START,
            end=OOS_END,
        )
        unseen_metrics[name] = summarize_intraday(r_u, n_tests=N_TRIALS)

    # 8. IEX check (2020-08-03 .. 2026-10-30): signals on IEX vs signals on SIP, executed on SIP
    print("8. Running IEX vs SIP signal verification (2020-08-03 .. 2026-10-30)...")
    bars_iex_full = {
        s: _slice_by_date(load_cached_minute_bars(s, "iex"), "2020-06-01", OOS_END) for s in SYMBOLS
    }
    iex_schedule = [t for t in base_schedule if t[0] >= "2020-08"]
    iex_sig_cache: dict[tuple[str, int, float], pd.DataFrame] = {}
    for s in SYMBOLS:
        iex_sig_cache[(s, D1_DEFAULT_PAIR[0], D1_DEFAULT_PAIR[1])] = generate_d1_signals(
            bars_iex_full[s], D1Params()
        )

    iex_frames = {
        "D1_cal": {
            s: _stitch_monthly_signals(bars_iex_full[s], iex_schedule, iex_sig_cache, s)
            for s in SYMBOLS
        },
        "D1_def": {s: iex_sig_cache[(s, D1_DEFAULT_PAIR[0], D1_DEFAULT_PAIR[1])] for s in SYMBOLS},
        "D1b": {s: generate_d1b_signals(bars_iex_full[s], D1bParams()) for s in SYMBOLS},
    }
    iex_comp: dict[str, dict[str, dict]] = {}
    for name in ("D1_cal", "D1_def", "D1b"):
        r_sip_w = run_intraday(
            panel_full,
            sig_objs[name],
            _cfg_for(name, cfg_judged),
            start=IEX_START,
            end=OOS_END,
        )
        r_iex_w = run_intraday(
            panel_full,
            IntradaySignals.from_frames(iex_frames[name], panel_full),
            _cfg_for(name, cfg_judged),
            start=IEX_START,
            end=OOS_END,
        )
        iex_comp[name] = {
            "sip": summarize_intraday(r_sip_w, n_tests=N_TRIALS),
            "iex": summarize_intraday(r_iex_w, n_tests=N_TRIALS),
        }

    # 9. Evaluate Gate 1 B criteria for D1_cal, D1_def, D1b
    d2_sharpe = float(metrics_judged["D2"]["sharpe"])
    criteria_by_name = {
        "D1_cal": evaluate_gate1_daytrading(
            oos=metrics_judged["D1_cal"],
            stress_expectancy_r=float(res_stress["D1_cal"].trades["r_multiple"].mean()),
            dsr_value=float(dsr_by_name["D1_cal"]["dsr"]),
            random_pct_beaten=float(rd_lo_summary["D1_cal"]["pct_beaten"]),
            varied_expectancies=varied_exp["D1_cal"],
            d2_sharpe=d2_sharpe,
        ),
        "D1_def": evaluate_gate1_daytrading(
            oos=metrics_judged["D1_def"],
            stress_expectancy_r=float(res_stress["D1_def"].trades["r_multiple"].mean()),
            dsr_value=float(dsr_by_name["D1_def"]["dsr"]),
            random_pct_beaten=float(rd_lo_summary["D1_def"]["pct_beaten"]),
            varied_expectancies=varied_exp["D1_def"],
            d2_sharpe=d2_sharpe,
        ),
        "D1b": evaluate_gate1_daytrading(
            oos=metrics_judged["D1b"],
            stress_expectancy_r=float(res_stress["D1b"].trades["r_multiple"].mean()),
            dsr_value=float(dsr_by_name["D1b"]["dsr"]),
            random_pct_beaten=float(rd_lo_summary["D1b"]["pct_beaten"]),
            varied_expectancies=varied_exp["D1b"],
            d2_sharpe=d2_sharpe,
            unseen_expectancy_r=float(unseen_metrics["D1b"]["expectancy_r"]),
        ),
    }

    bh = _buy_and_hold_metrics(bars_full, OOS_START, OOS_END)

    # Print summary to console
    print("\n=== REZUMAT OOS (2018-01-02 .. 2026-10-30, Long-Only, Stock Costs) ===")
    for name in ("D1_cal", "D1_def", "D1b", "D2"):
        m = metrics_judged[name]
        st_r = float(res_stress[name].trades["r_multiple"].mean())
        print(
            f"{name:8s} | Trades={m['n_trades']:4d} | CAGR={m['cagr']:6.2%} | "
            f"Sharpe={m['sharpe']:5.2f} | MaxDD={m['max_drawdown']:5.2%} | "
            f"PF={m['profit_factor']:4.2f} | "
            f"E[R]={m['expectancy_r']:+.4f}R (t={m['t_stat']:.2f}) | "
            f"E[R]x1.5={st_r:+.4f}R | DSR={dsr_by_name[name]['dsr']:.1%} | "
            f"RandBeat={rd_lo_summary[name]['pct_beaten']:.1%}"
        )
    for cname, crits in criteria_by_name.items():
        n_pass = sum(1 for c in crits if c.passed)
        verdict = "PASS" if passes(crits) else "FAIL"
        print(f"Verdict {cname}: {verdict} ({n_pass}/{len(crits)} criterii)")

    # Write markdown report
    report_path = Path("reports/gate1_daytrading.md")
    report_path.write_text(
        _format_report(
            cal_records=cal_records,
            metrics_judged=metrics_judged,
            res_stress=res_stress,
            metrics_ls=metrics_ls,
            metrics_cfd=metrics_cfd,
            years_judged=years_judged,
            dsr_by_name=dsr_by_name,
            sr_var_used=sr_var_used,
            rd_lo_summary=rd_lo_summary,
            rd_ls_summary=rd_ls_summary,
            varied_exp=varied_exp,
            unseen_metrics=unseen_metrics,
            iex_comp=iex_comp,
            criteria_by_name=criteria_by_name,
            bh=bh,
            elapsed_sec=time.perf_counter() - t0,
        ),
        encoding="utf-8",
    )
    print(f"\nWrote {report_path} in {time.perf_counter() - t0:.1f}s.")


def _format_report(
    *,
    cal_records,
    metrics_judged,
    res_stress,
    metrics_ls,
    metrics_cfd,
    years_judged,
    dsr_by_name,
    sr_var_used,
    rd_lo_summary,
    rd_ls_summary,
    varied_exp,
    unseen_metrics,
    iex_comp,
    criteria_by_name,
    bh,
    elapsed_sec,
) -> str:
    lines: list[str] = []
    a = lines.append

    a("# Raport Poarta 1 B — Day Trading Intraday SPY & QQQ (Faza B)")
    a("")
    a("**Data rulării:** 4 noiembrie 2026  ")
    a("**Fereastra OOS evaluată:** `2018-01-02 → 2026-10-30` (2.221 sesiuni NYSE, 106 luni)  ")
    a(
        "**Fereastra de calibrare inițială / warmup:** "
        "`2016-01-04 → 2017-12-29` (502 sesiuni NYSE)  "
    )
    a(
        "**Varianta judecată (D24, D29):** `SPY + QQQ`, `long_only=True`, `max_exposure=1.0`, "
        "acțiuni fracționare, `BOT_CAPITAL=500 $`, costuri `stock` (D25), veto FOMC (±30 min), "
        "`max_risk_per_trade=0.5%`, cel mult 50% din capital pe simbol.  "
    )
    a(
        "**Reguli și praguri pre-înregistrate:** `D29` și `D29b` în `docs/DECISIONS.md` "
        "(N = 9 încercări)."
    )
    a("")

    # Verdict table
    a("## 1. Verdict Poarta 1 B")
    a("")
    any_pass = any(passes(c) for c in criteria_by_name.values())
    verdict_all = "PASS" if any_pass else "FAIL"
    a(f"**Verdict general Poarta 1 B (criteriile stricte din D29/D29b):** **{verdict_all}**")
    a("")
    a(
        "> **Notă operațională (Decizia proprietarului, 4.11.2026):** Indiferent de scorul "
        "Porții 1 B pe backtest, construim botul complet pe **Alpaca Paper** "
        "(`B4 → B5 → B6c`), unde nu se riscă niciun ban real, iar botul învață zilnic din "
        "greșeli (`autopsy.py`, `daily_learner.py`, `meta_label.py`). "
        "Doar trecerea la bani reali rămâne blocată de Poarta 2."
    )
    a("")

    labels = {
        "D1_cal": "D1 (calibrat lunar 24m)",
        "D1_def": "D1 (default L=14, m=1.0)",
        "D1b": "D1b (VWAP & Ladder #1, Maróy 2025)",
        "D2": "D2 (ORB 5m, martor)",
    }

    for key in ("D1_cal", "D1_def", "D1b"):
        crits = criteria_by_name[key]
        n_ok = sum(1 for c in crits if c.passed)
        verdict_str = "PASS" if passes(crits) else "FAIL"
        a(f"### {labels[key]} — **{verdict_str}** ({n_ok}/{len(crits)} criterii îndeplinite)")
        a("")
        a("| # | Criteriu | Valoare obținută | Prag D29/D29b | Status |")
        a("|---|---|---|---|---|")
        for c in crits:
            st = "PASS" if c.passed else "FAIL"
            a(f"| {c.number} | {c.name} | {c.value} | {c.threshold} | **{st}** |")
        a("")

    # Section 2: Overall OOS comparison
    a("## 2. Metrici OOS principale (`2018-01-02 → 2026-10-30`, varianta judecată Long-Only)")
    a("")
    a(
        "| Strategie | Tranzacții | Win Rate | Profit Factor | E[R] net | "
        "t-stat (p Bonf. ×9) | E[R] cost ×1,5 | CAGR | Sharpe (√252) | "
        "Max DD | DSR (N=9) | Capital final (din 500 $) |"
    )
    a("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    for key in ("D1_cal", "D1_def", "D1b", "D2"):
        m = metrics_judged[key]
        st_r = float(res_stress[key].trades["r_multiple"].mean())
        dsr_v = float(dsr_by_name[key]["dsr"])
        fin_eq = INITIAL_CAPITAL * (1.0 + m["total_return"])
        a(
            f"| {labels[key]} | {m['n_trades']} | {m['win_rate']:.1%} | "
            f"{m['profit_factor']:.2f} | {m['expectancy_r']:+.4f}R | "
            f"{m['t_stat']:.2f} ({m['p_bonferroni']:.3f}) | "
            f"{st_r:+.4f}R | {m['cagr']:.2%} | {m['sharpe']:.2f} | "
            f"{m['max_drawdown']:.2%} | {dsr_v:.1%} | {fin_eq:.2f} $ |"
        )
    for bname, bm in bh.items():
        fin_eq = INITIAL_CAPITAL * (1.0 + bm["total_return"])
        a(
            f"| Buy & Hold {bname} | — | — | — | — | — | — | "
            f"{bm['cagr']:.2%} | {bm['sharpe']:.2f} | "
            f"{bm['max_drawdown']:.2%} | — | {fin_eq:.2f} $ |"
        )
    a("")
    a(
        f"*Notă DSR:* `sr_variance = {sr_var_used:.6f}` (`max(1/(T-1), var_empirică)` "
        f"pe T = 2.221 zile OOS). "
        f"Riscul mediu pe tranzacție (`avg_risk_pct`) a fost: "
        f"D1_cal `{metrics_judged['D1_cal']['avg_risk_pct']:.3%}`, "
        f"D1_def `{metrics_judged['D1_def']['avg_risk_pct']:.3%}`, "
        f"D1b `{metrics_judged['D1b']['avg_risk_pct']:.3%}`, "
        f"D2 `{metrics_judged['D2']['avg_risk_pct']:.3%}`. "
        f"Zile cu pierdere sub −2%: D1_cal `{metrics_judged['D1_cal']['loss_days_2pct']}`, "
        f"D1_def `{metrics_judged['D1_def']['loss_days_2pct']}`, "
        f"D1b `{metrics_judged['D1b']['loss_days_2pct']}`, "
        f"D2 `{metrics_judged['D2']['loss_days_2pct']}`."
    )
    a("")

    # Section 3: Yearly returns
    a("## 3. Randamente pe ani calendaristici (`2018–2026`, Long-Only)")
    a("")
    years_idx = list(years_judged["D1_cal"].index)
    yr_cols = " | ".join(str(y) for y in years_idx)
    header = f"| Strategie | {yr_cols} | Ani > 0 | Cel mai slab an |"
    sep = "|---|" + "---:|" * (len(years_idx) + 2)
    a(header)
    a(sep)
    for key in ("D1_cal", "D1_def", "D1b", "D2"):
        ys = years_judged[key]
        m = metrics_judged[key]
        row_vals = " | ".join(f"{float(ys.loc[y]):+.1%}" for y in years_idx)
        n_pos = int((ys > 0).sum())
        a(
            f"| {labels[key]} | {row_vals} | "
            f"{n_pos}/{len(years_idx)} ({m['pct_years_positive']:.0%}) | "
            f"{m['worst_year']:+.1%} |"
        )
    a("")

    # Section 4: Informative variants (Long+Short 2x & CFD costs)
    a("## 4. Variante informative: Long+Short (expunere 2×) și costuri CFD")
    a("")
    a("### 4.1 Long+Short (`long_only=False, max_exposure=2.0, cost_variant='stock'`)")
    a("")
    a(
        "| Strategie | Tranzacții (Long / Short) | Win Rate | PF | E[R] net | "
        "t-stat | CAGR | Sharpe | Max DD | Capital final |"
    )
    a("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    for key in ("D1_cal", "D1_def", "D1b", "D2"):
        m = metrics_ls[key]
        fin_eq = INITIAL_CAPITAL * (1.0 + m["total_return"])
        a(
            f"| {labels[key]} | {m['n_trades']} ({m['n_long']}L / {m['n_short']}S) | "
            f"{m['win_rate']:.1%} | {m['profit_factor']:.2f} | {m['expectancy_r']:+.4f}R | "
            f"{m['t_stat']:.2f} | {m['cagr']:.2%} | {m['sharpe']:.2f} | "
            f"{m['max_drawdown']:.2%} | {fin_eq:.2f} $ |"
        )
    a("")
    a("### 4.2 Costuri CFD (`long_only=True, cost_variant='cfd'`)")
    a("")
    a(
        "| Strategie | Tranzacții | Win Rate | PF | E[R] net | t-stat | "
        "CAGR | Sharpe | Max DD | Capital final |"
    )
    a("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    for key in ("D1_cal", "D1_def", "D1b", "D2"):
        m = metrics_cfd[key]
        fin_eq = INITIAL_CAPITAL * (1.0 + m["total_return"])
        a(
            f"| {labels[key]} | {m['n_trades']} | {m['win_rate']:.1%} | "
            f"{m['profit_factor']:.2f} | {m['expectancy_r']:+.4f}R | "
            f"{m['t_stat']:.2f} | {m['cagr']:.2%} | "
            f"{m['sharpe']:.2f} | {m['max_drawdown']:.2%} | {fin_eq:.2f} $ |"
        )
    a("")

    # Section 5: Random-direction test
    a("## 5. Testul cu direcție aleatoare (1.000 rulări, seed 42, D27)")
    a("")
    a(
        "| Strategie | Variantă | E[R] replay strategie | p5 aleator | "
        "p50 aleator | p95 aleator | % rulări bătute | p-value |"
    )
    a("|---|---|---:|---:|---:|---:|---:|---:|")
    for key in ("D1_cal", "D1_def", "D1b", "D2"):
        rlo = rd_lo_summary[key]
        rls = rd_ls_summary[key]
        a(
            f"| {labels[key]} | Long-Only (judecat) | {rlo['actual_expectancy_r']:+.4f}R | "
            f"{rlo['random_p5']:+.4f}R | {rlo['random_p50']:+.4f}R | {rlo['random_p95']:+.4f}R | "
            f"**{rlo['pct_beaten']:.1%}** | {rlo['p_value']:.4f} |"
        )
        a(
            f"| {labels[key]} | Long+Short (informativ) | {rls['actual_expectancy_r']:+.4f}R | "
            f"{rls['random_p5']:+.4f}R | {rls['random_p50']:+.4f}R | {rls['random_p95']:+.4f}R | "
            f"{rls['pct_beaten']:.1%} | {rls['p_value']:.4f} |"
        )
    a("")

    # Section 6: +/-20% Parameter perturbations
    a("## 6. Stabilitate la ±20% pe parametri (Criteriul 6)")
    a("")
    for key in ("D1_cal", "D1_def", "D1b"):
        a(f"### {labels[key]}")
        a("")
        a("| Perturbație parametru | Expectancy E[R] net OOS | Status (> 0) |")
        a("|---|---:|---|")
        for p_label, val in varied_exp[key].items():
            ok = "PASS" if val > 0 else "FAIL"
            a(f"| `{p_label}` | {val:+.4f}R | **{ok}** |")
        a("")

    # Section 7: Unseen window for D1b (2024-10-01 .. 2026-10-30)
    a("## 7. Fereastra nevăzută de autorul D1b (`2024-10-01 → 2026-10-30`, D29b)")
    a("")
    a(
        "În Maróy (2025), parametrii `VWAP & Ladder #1` au fost optimizați pe QQQ "
        "`2014-10-01 → 2024-10-01`. Performanța pur out-of-sample față de fereastra autorului este:"
    )
    a("")
    a("| Strategie | Tranzacții | Win Rate | PF | E[R] net | t-stat | CAGR | Sharpe | Max DD |")
    a("|---|---:|---:|---:|---:|---:|---:|---:|---:|")
    for key in ("D1_cal", "D1_def", "D1b", "D2"):
        m = unseen_metrics[key]
        a(
            f"| {labels[key]} | {m['n_trades']} | {m['win_rate']:.1%} | "
            f"{m['profit_factor']:.2f} | {m['expectancy_r']:+.4f}R | "
            f"{m['t_stat']:.2f} | {m['cagr']:.2%} | "
            f"{m['sharpe']:.2f} | {m['max_drawdown']:.2%} |"
        )
    a("")

    # Section 8: IEX vs SIP verification (2020-08-03 .. 2026-10-30)
    a("## 8. Verificarea semnalelor IEX cu execuție SIP (`2020-08-03 → 2026-10-30`, D26/D29)")
    a("")
    a(
        "| Strategie | Sursă semnale | Tranzacții | E[R] net | PF | Sharpe | "
        "CAGR | Max DD | Raport E[R] IEX / SIP |"
    )
    a("|---|---|---:|---:|---:|---:|---:|---:|---:|")
    for key in ("D1_cal", "D1_def", "D1b"):
        ms = iex_comp[key]["sip"]
        mi = iex_comp[key]["iex"]
        ratio = (
            mi["expectancy_r"] / ms["expectancy_r"]
            if ms["expectancy_r"] and ms["expectancy_r"] > 0
            else float("nan")
        )
        ratio_str = f"{ratio:.1%}" if np.isfinite(ratio) else "n/a"
        a(
            f"| {labels[key]} | SIP (referință) | {ms['n_trades']} | {ms['expectancy_r']:+.4f}R | "
            f"{ms['profit_factor']:.2f} | {ms['sharpe']:.2f} | {ms['cagr']:.2%} | "
            f"{ms['max_drawdown']:.2%} | — |"
        )
        a(
            f"| {labels[key]} | IEX (exec. SIP) | {mi['n_trades']} | {mi['expectancy_r']:+.4f}R | "
            f"{mi['profit_factor']:.2f} | {mi['sharpe']:.2f} | {mi['cagr']:.2%} | "
            f"{mi['max_drawdown']:.2%} | **{ratio_str}** |"
        )
    a("")

    # Section 9: Monthly calibration summary
    a("## 9. Distribuția perechilor `(L, m)` alese în calibrarea lunară D1 (106 luni OOS)")
    a("")
    pair_counts: dict[tuple[int, float], int] = {}
    for r in cal_records:
        pair_counts[(r.lookback_days, r.band_mult)] = (
            pair_counts.get((r.lookback_days, r.band_mult), 0) + 1
        )
    a("| Pereche `(L, m)` | Luni alese (din 106) | Pondere |")
    a("|---|---:|---:|")
    for (L, m), cnt in sorted(pair_counts.items(), key=lambda x: (-x[1], x[0])):
        a(f"| `L={L}, m={m}` | {cnt} | {cnt / len(cal_records):.1%} |")
    a("")
    a(f"*Timp total de execuție evaluare Poarta 1 B:* `{elapsed_sec:.1f} s`.")
    a("")
    return "\n".join(lines)


if __name__ == "__main__":
    main()
