"""AI & statistical learning modules for Theo Trading Bot (Faza B, B4)."""

from src.ai.autopsy import build_autopsy_record, classify_trade_outcome, generate_trade_lesson
from src.ai.daily_learner import compute_hourly_multipliers, retrain_on_daily_trades
from src.ai.meta_label import (
    FEATURE_COLUMNS,
    apply_meta_filter,
    build_meta_dataset,
    compute_feature_frame,
    make_meta_pipeline,
    purged_walk_forward_probs,
)
from src.ai.veto import check_news_veto, fetch_recent_news

__all__ = [
    "FEATURE_COLUMNS",
    "apply_meta_filter",
    "build_autopsy_record",
    "build_meta_dataset",
    "check_news_veto",
    "classify_trade_outcome",
    "compute_feature_frame",
    "compute_hourly_multipliers",
    "fetch_recent_news",
    "generate_trade_lesson",
    "make_meta_pipeline",
    "purged_walk_forward_probs",
    "retrain_on_daily_trades",
]
