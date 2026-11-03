"""Faza B metrics and the random-direction test (docs/PLAN_DAYTRADING.md, Poarta 1 B).

- Expectancy in R with a one-sided t-stat (normal approximation, fine for >= 300 trades) and a
  Bonferroni-adjusted p-value for N = 9 tests; the gate threshold is t >= 2.6.
- Deflated Sharpe Ratio (Bailey & Lopez de Prado 2014) on daily returns, for N trials.
- Yearly returns, days losing more than 2%, and the usual equity/trade metrics.
- Random-direction test: same entries, stop distances and exit times, coin-flip direction.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from statistics import NormalDist

import numpy as np
import pandas as pd

from src.backtest.intraday_costs import cost_per_side
from src.backtest.intraday_engine import IntradayConfig, IntradayPanel, IntradayResult
from src.backtest.metrics import daily_returns, equity_metrics, trade_metrics

N_TESTS = 9
T_STAT_MIN = 2.6
EULER_GAMMA = 0.5772156649015329
LOSS_DAY = 0.02
_NORMAL = NormalDist()


def r_stats(r, n_tests: int = N_TESTS) -> dict:
    """Expectancy in R, its t-stat and one-sided p-value, Bonferroni-adjusted for n_tests."""
    r = np.asarray(r, dtype=float)
    n = r.size
    out = {"expectancy_r": float(r.mean()) if n else np.nan, "std_r": np.nan, "t_stat": np.nan}
    out |= {"p_value": np.nan, "p_bonferroni": np.nan}
    if n < 2:
        return out
    std = float(r.std(ddof=1))
    if std == 0:
        return out
    t = out["expectancy_r"] / (std / math.sqrt(n))
    p = 1.0 - _NORMAL.cdf(t)
    return out | {"std_r": std, "t_stat": t, "p_value": p, "p_bonferroni": min(1.0, p * n_tests)}


def deflated_sharpe(returns, n_trials: int = N_TESTS, sr_variance: float | None = None) -> dict:
    """Probability that the true Sharpe is above the best of `n_trials` unskilled trials.

    Sharpe per period (not annualized). `sr_variance` is the variance of the Sharpe ratios across
    the trials; by default 1 / (T - 1), the estimator's variance when every trial has true SR 0.
    With n_trials = 1 this is the Probabilistic Sharpe Ratio against 0.
    """
    x = np.asarray(returns, dtype=float)
    t = x.size
    sd = x.std(ddof=1) if t > 1 else 0.0
    if sd == 0:
        return {
            "sharpe_period": np.nan,
            "sr0": np.nan,
            "skew": np.nan,
            "kurtosis": np.nan,
            "dsr": np.nan,
        }
    sr = float(x.mean() / sd)
    z = (x - x.mean()) / x.std(ddof=0)
    skew, kurt = float((z**3).mean()), float((z**4).mean())
    var = 1.0 / (t - 1) if sr_variance is None else sr_variance
    sr0 = 0.0
    if n_trials > 1:
        sr0 = math.sqrt(var) * (
            (1 - EULER_GAMMA) * _NORMAL.inv_cdf(1 - 1 / n_trials)
            + EULER_GAMMA * _NORMAL.inv_cdf(1 - 1 / (n_trials * math.e))
        )
    denom = 1 - skew * sr + (kurt - 1) / 4 * sr**2
    dsr = _NORMAL.cdf((sr - sr0) * math.sqrt(t - 1) / math.sqrt(denom))
    return {"sharpe_period": sr, "sr0": sr0, "skew": skew, "kurtosis": kurt, "dsr": dsr}


def yearly_returns(equity: pd.Series, initial: float) -> pd.Series:
    """Compounded return of each calendar year; the first year starts from `initial`."""
    ends = equity.groupby(equity.index.year).last()
    prev = ends.shift(1)
    prev.iloc[0] = initial
    return (ends / prev - 1.0).rename("return")


def summarize_intraday(result: IntradayResult, n_tests: int = N_TESTS) -> dict:
    """All Poarta 1 B metrics of one run."""
    init = result.config.initial_capital
    eq, trades = result.equity, result.trades
    rets = daily_returns(eq, init)
    years = yearly_returns(eq, init)
    stats = r_stats(trades["r_multiple"], n_tests)
    return {
        **equity_metrics(eq, init),
        **trade_metrics(trades),
        **{k: stats[k] for k in ("std_r", "t_stat", "p_value", "p_bonferroni")},
        "dsr": deflated_sharpe(rets, n_tests)["dsr"],
        "loss_days_2pct": int((rets < -LOSS_DAY).sum()),
        "worst_day": float(rets.min()),
        "pct_years_positive": float((years > 0).mean()),
        "worst_year": float(years.min()),
        "n_long": int((trades["direction"] == "long").sum()),
        "n_short": int((trades["direction"] == "short").sum()),
        "avg_risk_pct": float(trades["risk_pct"].mean()) if len(trades) else np.nan,
    }


def direction_outcomes(
    trades: pd.DataFrame, panel: IntradayPanel, config: IntradayConfig
) -> pd.DataFrame:
    """R of each trade replayed long and short under one rule, for the random-direction test.

    Same entry bar and Open, same initial stop distance (mirrored for the other direction); the
    replay exits at its own stop (worst case inside a bar, the Open on a gap) or at the Close of
    the symbol's last bar of the session. Costs as in the run. The replay ignores the trade's
    real exit: an exit time chosen by one direction's stop would handicap the other direction.
    Columns: r_long, r_short and r_own (the replay in the trade's own direction).
    """
    col = {s: j for j, s in enumerate(panel.symbols)}
    session_of = np.searchsorted(panel.bounds[:, 0], trades["entry_bar"].to_numpy(), "right") - 1
    out = np.empty((len(trades), 2))
    for n, t in enumerate(trades.itertuples(index=False)):
        j, e = col[t.symbol], t.entry_bar
        last = panel.last_bar[session_of[n], j]
        op, hi, lo = (a[e : last + 1, j] for a in (panel.open, panel.high, panel.low))
        cost = cost_per_side(t.symbol, config.cost_variant, config.cost_stress)
        for k, d in enumerate((1, -1)):
            stop = t.entry_open - d * t.initial_risk
            hit = np.flatnonzero(((lo if d == 1 else hi) - stop) * d <= 0)
            if hit.size:
                b = hit[0]
                price = op[b] if b > 0 and (op[b] - stop) * d <= 0 else stop
            else:
                price = panel.close[last, j]
            out[n, k] = (d * (price - t.entry_open) - 2 * cost) / t.initial_risk
    res = pd.DataFrame(out, columns=["r_long", "r_short"], index=trades.index)
    res["r_own"] = res["r_long"].where(trades["direction"] == "long", res["r_short"])
    return res


@dataclass
class RandomDirectionResult:
    actual: float  # expectancy in R of the strategy
    random: np.ndarray  # expectancy of each random run

    def summary(self) -> dict:
        valid = self.random[np.isfinite(self.random)]
        return {
            "n_runs": len(valid),
            "actual_expectancy_r": self.actual,
            "pct_beaten": float((self.actual > valid).mean()),
            "p_value": float((1 + (valid >= self.actual).sum()) / (len(valid) + 1)),
            **{f"random_p{p}": float(np.percentile(valid, p)) for p in (5, 50, 95)},
        }


def random_direction_test(
    outcomes: pd.DataFrame,
    actual: float | None = None,
    n_runs: int = 1000,
    seed: int = 42,
    long_only: bool = False,
) -> RandomDirectionResult:
    """Expectancy of `n_runs` coin-flip directions over the replays in `outcomes`.

    Both directions: each run flips every trade long or short; `actual` defaults to the mean
    r_own (the strategy's own directions under the same replay rule). Long-only (D24): `outcomes`
    holds the replays of the candidate trades of the long+short run; each run flips a coin per
    candidate and keeps only the longs, and `actual` (required) is the mean r_own of the
    long-only run, so its long entries are compared with random candidate moments.
    """
    r = outcomes[["r_long", "r_short"]].to_numpy(dtype=float)
    if len(r) == 0:
        raise ValueError("the random-direction test needs at least one trade")
    if actual is None:
        if long_only:
            raise ValueError("long_only needs the long-only run's replay expectancy as `actual`")
        actual = float(outcomes["r_own"].mean())
    rng = np.random.default_rng(seed)
    pick_long = rng.random((n_runs, len(r))) < 0.5
    if long_only:
        counts = pick_long.sum(axis=1)
        sums = (pick_long * r[:, 0]).sum(axis=1)
        random = np.where(counts > 0, sums / np.maximum(counts, 1), np.nan)
    else:
        random = np.where(pick_long, r[:, 0], r[:, 1]).mean(axis=1)
    return RandomDirectionResult(actual=float(actual), random=random)
