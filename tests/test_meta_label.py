"""Unit and look-ahead tests for meta-labeling and daily learning (Faza B, B4)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from src.ai.daily_learner import compute_hourly_multipliers, retrain_on_daily_trades
from src.ai.meta_label import (
    FEATURE_COLUMNS,
    apply_meta_filter,
    build_meta_dataset,
    compute_feature_frame,
    purged_walk_forward_probs,
)
from src.backtest.lookahead import assert_no_lookahead


def _load_fixture_bars() -> pd.DataFrame:
    df = pd.read_csv("tests/fixtures/minute_spy_sip_2016-11.csv", index_col=0, parse_dates=True)
    df.index = pd.to_datetime(df.index, utc=True).tz_convert("America/New_York")
    return df


def test_compute_feature_frame_has_exact_columns_and_no_lookahead():
    bars = _load_fixture_bars()
    ff = compute_feature_frame(bars.iloc[:120], lookback=1, mult=1.0, symbol="SPY")
    assert tuple(ff.columns) == FEATURE_COLUMNS
    assert len(ff) == 120
    assert np.isfinite(ff.to_numpy()).all()

    assert_no_lookahead(
        lambda prices: {
            s: compute_feature_frame(df, lookback=1, mult=1.0, symbol=s) for s, df in prices.items()
        },
        {"SPY": bars},
        n_checks=8,
        min_history=395,
        columns=FEATURE_COLUMNS,
    )


def test_build_meta_dataset_and_apply_meta_filter():
    bars = _load_fixture_bars()
    t1 = bars.index[40]
    t2 = bars.index[100]
    trades = pd.DataFrame(
        [
            {
                "symbol": "SPY",
                "signal_time": t1,
                "entry_time": bars.index[41],
                "exit_time": bars.index[60],
                "initial_risk": 0.50,
                "r_multiple": 1.25,
            },
            {
                "symbol": "SPY",
                "signal_time": t2,
                "entry_time": bars.index[101],
                "exit_time": bars.index[120],
                "initial_risk": 0.40,
                "r_multiple": -1.00,
            },
        ]
    )
    X, y = build_meta_dataset(bars, trades, lookback=1, mult=1.0)
    assert tuple(X.columns) == FEATURE_COLUMNS
    assert list(y) == [1, 0]

    signals = pd.DataFrame(
        {
            "entry": [1, 1],
            "stop": [200.0, 200.0],
            "entry_reason": ["D1b long 1", "D1b long 2"],
        },
        index=pd.DatetimeIndex([t1, t2]),
    )
    probs = pd.Series([0.72, 0.41], index=signals.index)
    filtered = apply_meta_filter(signals, probs, threshold=0.55)
    assert filtered.loc[t1, "entry"] == 1
    assert "[ML p=0.72]" in filtered.loc[t1, "entry_reason"]
    assert filtered.loc[t2, "entry"] == 0


def test_purged_walk_forward_probs_respects_embargo_and_never_uses_test_month():
    rng = np.random.default_rng(42)
    dates = pd.date_range("2022-01-05", "2024-06-25", freq="7D", tz="America/New_York")
    n = len(dates)
    X = pd.DataFrame(
        rng.normal(0.0, 1.0, size=(n, len(FEATURE_COLUMNS))),
        index=dates,
        columns=FEATURE_COLUMNS,
    )
    # Signal 0 strongly predicts win in training
    y = pd.Series((X["minute_of_day"] > 0).astype(int), index=dates)
    exit_times = pd.Series(dates + pd.Timedelta(hours=2), index=dates)

    probs = purged_walk_forward_probs(X, y, exit_times, train_months=12, embargo_days=5)
    # First 12 months must be NaN (pure training warmup)
    first_year_mask = dates < pd.Timestamp("2023-01-01", tz="America/New_York")
    assert probs.loc[first_year_mask].isna().all()
    # Later months have valid OOS probabilities in [0, 1]
    later = probs.loc[~first_year_mask].dropna()
    assert len(later) > 20
    assert ((later >= 0.0) & (later <= 1.0)).all()


def test_retrain_on_daily_trades_penalizes_losing_pattern(tmp_path: Path):
    rng = np.random.default_rng(7)
    n_hist = 60
    hist_X = pd.DataFrame(
        rng.normal(0.0, 1.0, size=(n_hist, len(FEATURE_COLUMNS))),
        columns=FEATURE_COLUMNS,
    )
    # Historically, positive cost_to_risk had a positive win rate
    hist_y = pd.Series((hist_X["cost_to_risk"] > -0.2).astype(int))

    # First fit without new losing trades
    empty_X = pd.DataFrame(columns=FEATURE_COLUMNS, dtype=float)
    empty_y = pd.Series([], dtype=int)
    res_before = retrain_on_daily_trades(hist_X, hist_y, empty_X, empty_y)

    # Probe pattern inside normal feature scale
    probe = pd.DataFrame([{col: 0.0 for col in FEATURE_COLUMNS}])
    probe["cost_to_risk"] = 1.5
    probe["minute_of_day"] = 1.0
    prob_before = float(res_before["pipeline"].predict_proba(probe)[0, 1])

    # Now 15 new trades with that exact pattern all lose (y = 0)
    new_X = pd.concat([probe] * 15, ignore_index=True)
    new_y = pd.Series(np.zeros(15, dtype=int))

    model_file = tmp_path / "meta_model.joblib"
    stats_file = tmp_path / "learning_stats.json"
    res_after = retrain_on_daily_trades(
        hist_X,
        hist_y,
        new_X,
        new_y,
        model_path=model_file,
        stats_path=stats_file,
    )
    prob_after = float(res_after["pipeline"].predict_proba(probe)[0, 1])

    assert prob_after < prob_before
    assert model_file.exists()
    assert stats_file.exists()
    assert res_after["trained_samples"] == n_hist + 15


def test_compute_hourly_multipliers_scales_down_losing_hours():
    trades = pd.DataFrame(
        {
            "entry_time": [f"2026-10-{d:02d} 10:12:00-04:00" for d in range(1, 8)]
            + [f"2026-10-{d:02d} 14:02:00-04:00" for d in range(1, 8)],
            "r_multiple": [0.4, 0.5, 0.2, 0.3, 0.6, 0.1, 0.2]
            + [-0.4, -0.3, -0.5, -0.2, -0.4, -0.3, -0.3],
        }
    )
    mults = compute_hourly_multipliers(trades, min_trades_per_bucket=5)
    assert mults["10:00"] == 1.0
    assert 0.5 <= mults["14:00"] < 1.0
