"""Daily self-learning from mistakes at end of session (Faza B, B4).

Retrains the meta-labeling logistic pipeline on the combined history plus today's closed trades
with higher sample weight (`3.0`) on recent trades so repeated losing patterns get penalized
immediately, and updates `state/learning_stats.json` for the dashboard.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd

from src.ai.meta_label import FEATURE_COLUMNS, make_meta_pipeline
from src.state.store import atomic_write_json

RECENT_SAMPLE_WEIGHT = 3.0
OLD_SAMPLE_WEIGHT = 1.0
RECENT_WINDOW_TRADES = 40


def compute_hourly_multipliers(
    trades: pd.DataFrame,
    min_trades_per_bucket: int = 5,
    min_multiplier: float = 0.5,
) -> dict[str, float]:
    """Compute position size multipliers (0.5 .. 1.0) per NY hour based on rolling expectancy."""
    multipliers = {f"{h:02d}:00": 1.0 for h in range(9, 16)}
    if trades.empty or "entry_time" not in trades.columns or "r_multiple" not in trades.columns:
        return multipliers

    # utc=True: trade times mix -05:00 (EST) and -04:00 (EDT) offsets across DST changes
    entry_ts = pd.to_datetime(trades["entry_time"], utc=True, errors="coerce")
    hours = entry_ts.dt.tz_convert("America/New_York").dt.hour
    r_vals = pd.to_numeric(trades["r_multiple"], errors="coerce")

    for h in range(9, 16):
        bucket = r_vals.loc[hours == h]
        if len(bucket) < min_trades_per_bucket:
            continue
        mean_r = float(bucket.mean())
        if mean_r < 0.0:
            # Penalize losing hours proportionally down to min_multiplier (0.5)
            mult = max(min_multiplier, 1.0 + mean_r)
            multipliers[f"{h:02d}:00"] = round(float(mult), 3)
    return multipliers


def retrain_on_daily_trades(
    history_X: pd.DataFrame,
    history_y: pd.Series,
    new_X: pd.DataFrame,
    new_y: pd.Series,
    model_path: Path | str | None = None,
    stats_path: Path | str | None = None,
    base_threshold: float = 0.55,
) -> dict[str, Any]:
    """Append today's trades with 3x sample weight, retrain the meta-labeler, and save stats."""
    cols = [c for c in FEATURE_COLUMNS if c in history_X.columns] or list(history_X.columns)
    all_X = pd.concat([history_X.loc[:, cols], new_X.loc[:, cols]], axis=0)
    all_y = pd.concat([history_y.astype(int), new_y.astype(int)], axis=0)

    n_total = len(all_y)
    n_new = len(new_y)
    n_recent = min(n_total, max(n_new, RECENT_WINDOW_TRADES))

    weights = np.full(n_total, OLD_SAMPLE_WEIGHT, dtype=float)
    if n_recent > 0:
        weights[-n_recent:] = RECENT_SAMPLE_WEIGHT

    pipe = make_meta_pipeline()
    top_mistake_feature = cols[0] if cols else "none"
    if n_total >= 4 and all_y.nunique() >= 2:
        pipe.fit(all_X, all_y, clf__sample_weight=weights)
        coefs = pipe.named_steps["clf"].coef_[0]
        worst_idx = int(np.argmin(coefs))
        top_mistake_feature = str(cols[worst_idx])

    if model_path is not None:
        mpath = Path(model_path)
        mpath.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(pipe, mpath)

    recent_win_rate = float(all_y.iloc[-n_recent:].mean()) if n_recent > 0 else 0.0
    # Slightly tighten threshold if recent win rate dropped below 40%
    updated_threshold = (
        round(min(0.65, base_threshold + 0.03), 3)
        if recent_win_rate < 0.40 and n_recent >= 5
        else base_threshold
    )

    stats = {
        "trained_samples": int(n_total),
        "new_samples_today": int(n_new),
        "recent_win_rate": round(recent_win_rate, 4),
        "top_mistake_feature": top_mistake_feature,
        "updated_threshold": float(updated_threshold),
        "model_path": str(model_path) if model_path is not None else None,
    }
    if stats_path is not None:
        atomic_write_json(stats_path, stats)

    return {**stats, "pipeline": pipe}


__all__ = [
    "OLD_SAMPLE_WEIGHT",
    "RECENT_SAMPLE_WEIGHT",
    "RECENT_WINDOW_TRADES",
    "compute_hourly_multipliers",
    "retrain_on_daily_trades",
]
