"""Meta-labeling with Triple Barrier outcomes and Purged Walk-Forward CV (Faza B, B4).

Computes 10 strictly causal intraday features at `signal_time` (only using bars <= t),
trains a `StandardScaler + LogisticRegression` classifier with Purging + Embargo between
training and test windows, and filters low-probability entries (`prob < threshold`).
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from src.backtest.intraday_costs import cost_per_side
from src.strategies.intraday_d1 import _daily_volatility, _session_vwap, compute_noise_bands

FEATURE_COLUMNS: tuple[str, ...] = (
    "minute_of_day",
    "dist_from_band_bps",
    "dist_from_vwap_bps",
    "rv_30m",
    "sigma_14d",
    "overnight_gap_bps",
    "ret_since_open_bps",
    "vol_ratio_14d",
    "day_of_week",
    "cost_to_risk",
)


def make_meta_pipeline() -> Pipeline:
    """Create the standard regularized logistic regression pipeline for meta-labeling."""
    return Pipeline(
        [
            ("scaler", StandardScaler()),
            ("clf", LogisticRegression(C=0.5, max_iter=500, random_state=42)),
        ]
    )


def compute_feature_frame(
    bars: pd.DataFrame,
    lookback: int = 14,
    mult: float = 1.0,
    symbol: str = "SPY",
) -> pd.DataFrame:
    """Compute the 10 meta-labeling features for every bar t using only bars <= t."""
    if bars.empty:
        return pd.DataFrame(columns=FEATURE_COLUMNS, index=bars.index, dtype=float)

    idx = bars.index
    ny_idx = idx.tz_convert("America/New_York") if idx.tz is not None else idx
    days = pd.Series(ny_idx.tz_localize(None).normalize(), index=idx)
    minutes = pd.Series(ny_idx.hour * 60 + ny_idx.minute, index=idx, dtype=float)

    minute_of_day = minutes - (9 * 60 + 30)
    day_of_week = pd.Series(ny_idx.day_of_week, index=idx, dtype=float)

    bands = compute_noise_bands(bars, lookback=lookback, mult=mult)
    vwap = _session_vwap(bars, days)
    sigma_14d = pd.Series(
        _daily_volatility(bars, days, vol_lookback=lookback, ddof=1), index=idx, dtype=float
    ).fillna(0.01)

    close = bars["close"].astype(float)
    ub = bands["ub"].astype(float)
    lb = bands["lb"].astype(float)

    # Distance from active breakout band (UB if above VWAP, LB if below VWAP)
    active_band = pd.Series(np.where(close >= vwap, ub, lb), index=idx, dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        dist_from_band_bps = ((close / active_band - 1.0).abs() * 1e4).replace(
            [np.inf, -np.inf], np.nan
        )
        dist_from_vwap_bps = ((close / vwap - 1.0).abs() * 1e4).replace([np.inf, -np.inf], np.nan)

    # 30-minute realized volatility of 1-minute returns within each session
    ret_1m = close.groupby(days).pct_change()
    rv_30m = (
        ret_1m.groupby(days)
        .rolling(30, min_periods=5)
        .std(ddof=1)
        .reset_index(level=0, drop=True)
        .fillna(0.0)
    )

    # Session open and prior session close for overnight gap and intraday return
    session_open = bars["open"].astype(float).groupby(days).transform("first")
    daily_close = close.groupby(days).last()
    prev_close_by_day = daily_close.shift(1)
    prev_close = days.map(prev_close_by_day).astype(float)

    overnight_gap_bps = ((session_open / prev_close - 1.0) * 1e4).fillna(0.0)
    ret_since_open_bps = ((close / session_open - 1.0) * 1e4).fillna(0.0)

    # Cumulative session volume ratio vs trailing 14-session average at the same minute
    cum_vol = bars["volume"].astype(float).groupby(days).cumsum()
    day_min_df = pd.DataFrame({"day": days, "min": minutes.astype(int), "cum_vol": cum_vol})
    piv = day_min_df.pivot_table(index="day", columns="min", values="cum_vol", aggfunc="last")
    avg_cum_vol = piv.shift(1).rolling(window=lookback, min_periods=1).mean()
    avg_lookup = avg_cum_vol.stack(future_stack=True)
    keys = pd.MultiIndex.from_arrays([days, minutes.astype(int)], names=["day", "min"])
    hist_vol = keys.map(avg_lookup).to_numpy(dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        vol_ratio_14d = pd.Series(
            np.where(np.isfinite(hist_vol) & (hist_vol > 0), cum_vol.to_numpy() / hist_vol, 1.0),
            index=idx,
            dtype=float,
        )

    # Default initial risk estimate at bar t = distance to opposite band (or 0.5% of price)
    rt_cost = 2.0 * cost_per_side(symbol, "stock")
    band_risk = np.maximum((close - lb).abs(), close * 0.002)
    cost_to_risk = pd.Series(rt_cost / band_risk, index=idx, dtype=float)

    out = pd.DataFrame(
        {
            "minute_of_day": minute_of_day,
            "dist_from_band_bps": dist_from_band_bps.fillna(0.0),
            "dist_from_vwap_bps": dist_from_vwap_bps.fillna(0.0),
            "rv_30m": rv_30m,
            "sigma_14d": sigma_14d,
            "overnight_gap_bps": overnight_gap_bps,
            "ret_since_open_bps": ret_since_open_bps,
            "vol_ratio_14d": vol_ratio_14d.fillna(1.0),
            "day_of_week": day_of_week,
            "cost_to_risk": cost_to_risk.fillna(0.05),
        },
        index=idx,
    )
    return out.loc[:, list(FEATURE_COLUMNS)]


def build_meta_dataset(
    bars: pd.DataFrame | dict[str, pd.DataFrame],
    trades: pd.DataFrame,
    lookback: int = 14,
    mult: float = 1.0,
) -> tuple[pd.DataFrame, pd.Series]:
    """Extract the 10 features at each trade's `signal_time` and binary target `r_multiple > 0`."""
    if trades.empty:
        empty_x = pd.DataFrame(columns=FEATURE_COLUMNS, dtype=float)
        empty_y = pd.Series([], dtype=int, name="target")
        return empty_x, empty_y

    if isinstance(bars, pd.DataFrame):
        default_sym = str(trades["symbol"].iloc[0]) if "symbol" in trades.columns else "SPY"
        feat_by_sym = {
            default_sym: compute_feature_frame(
                bars, lookback=lookback, mult=mult, symbol=default_sym
            )
        }
    else:
        feat_by_sym = {
            sym: compute_feature_frame(df, lookback=lookback, mult=mult, symbol=sym)
            for sym, df in bars.items()
        }

    rows: list[pd.Series] = []
    targets: list[int] = []
    idx_list: list[pd.Timestamp] = []

    for row in trades.itertuples(index=False):
        sym = getattr(row, "symbol", next(iter(feat_by_sym)))
        sig_time = pd.Timestamp(row.signal_time)
        ff = feat_by_sym[sym]
        if sig_time in ff.index:
            feat_row = ff.loc[sig_time].copy()
        else:
            pos = int(ff.index.searchsorted(sig_time, side="right")) - 1
            if pos < 0:
                continue
            feat_row = ff.iloc[pos].copy()

        init_risk = float(getattr(row, "initial_risk", 0.0) or 0.0)
        if init_risk > 0:
            feat_row["cost_to_risk"] = (2.0 * cost_per_side(sym, "stock")) / init_risk

        rows.append(feat_row)
        targets.append(int(float(row.r_multiple) > 0.0))
        idx_list.append(sig_time)

    x_df = pd.DataFrame(rows, index=pd.DatetimeIndex(idx_list, name="signal_time"))
    x_df = x_df.loc[:, list(FEATURE_COLUMNS)].astype(float)
    y_ser = pd.Series(targets, index=x_df.index, dtype=int, name="target")
    return x_df, y_ser


def purged_walk_forward_probs(
    X: pd.DataFrame,
    y: pd.Series,
    exit_times: pd.Series,
    train_months: int = 24,
    embargo_days: int = 5,
    min_train_samples: int = 20,
) -> pd.Series:
    """Compute OOS predicted win probabilities with Purging + Embargo before each test month."""
    probs = pd.Series(np.nan, index=X.index, dtype=float, name="prob")
    if X.empty:
        return probs

    sig_idx = pd.DatetimeIndex(X.index)
    sig_naive = sig_idx.tz_convert("America/New_York").tz_localize(None) if sig_idx.tz else sig_idx
    exit_dt = pd.to_datetime(exit_times)
    exit_naive = (
        exit_dt.dt.tz_convert("America/New_York").dt.tz_localize(None)
        if exit_dt.dt.tz is not None
        else exit_dt
    ).to_numpy()

    periods = sig_naive.to_period("M")
    unique_months = sorted(periods.unique())
    if len(unique_months) <= train_months:
        return probs

    for m_idx in range(train_months, len(unique_months)):
        test_month = unique_months[m_idx]
        test_start = test_month.start_time
        train_start = test_start - pd.DateOffset(months=train_months)
        purge_cutoff = test_start - pd.Timedelta(days=embargo_days)

        train_mask = (
            (sig_naive >= train_start)
            & (sig_naive < purge_cutoff)
            & (exit_naive <= purge_cutoff.to_datetime64())
        )
        test_mask = periods == test_month

        if not np.any(test_mask) or int(np.sum(train_mask)) < min_train_samples:
            continue

        y_train = y.loc[train_mask]
        if y_train.nunique() < 2:
            probs.loc[test_mask] = float(y_train.mean())
            continue

        pipe = make_meta_pipeline()
        pipe.fit(X.loc[train_mask], y_train)
        probs.loc[test_mask] = pipe.predict_proba(X.loc[test_mask])[:, 1]

    return probs


def apply_meta_filter(
    signals: pd.DataFrame,
    probs: pd.Series,
    threshold: float = 0.55,
) -> pd.DataFrame:
    """Filter entry signals by OOS meta-labeling probability (`probs >= threshold`)."""
    out = signals.copy()
    dir_col = "entry" if "entry" in out.columns else "direction"
    aligned_probs = probs.reindex(out.index)

    has_entry = out[dir_col] != 0
    keep = has_entry & aligned_probs.notna() & (aligned_probs >= threshold)
    block = has_entry & ~keep

    out.loc[block, dir_col] = 0
    if "entry_reason" in out.columns:
        for ts in out.index[keep]:
            p_val = float(aligned_probs.loc[ts])
            out.loc[ts, "entry_reason"] = f"{out.loc[ts, 'entry_reason']} [ML p={p_val:.2f}]"
    return out


__all__ = [
    "FEATURE_COLUMNS",
    "apply_meta_filter",
    "build_meta_dataset",
    "compute_feature_frame",
    "make_meta_pipeline",
    "purged_walk_forward_probs",
]
