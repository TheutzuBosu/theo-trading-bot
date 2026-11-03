"""Strategy registry: parameters from config/strategies.yaml, signals as pure functions."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from functools import partial
from pathlib import Path

import yaml

from src.backtest.lookahead import Strategy
from src.config import settings
from src.strategies import s1_trend_breakout, s2_momentum_rotation, s3_rsi2_pullback, s4_macd_ema200
from src.strategies.common import StrategyParams

MODULES = {
    "S1": s1_trend_breakout,
    "S2": s2_momentum_rotation,
    "S3": s3_rsi2_pullback,
    "S4": s4_macd_ema200,
}


@dataclass(frozen=True)
class StrategySpec:
    name: str
    title: str
    params: StrategyParams
    signals: Strategy  # prices -> {symbol: signal frame}
    max_hold_bars: int | None = None  # pass to BacktestConfig


def load_params(path: Path | str | None = None) -> dict[str, dict]:
    """Raw parameters per strategy from the YAML file."""
    yaml_path = Path(path) if path is not None else settings.CONFIG_DIR / "strategies.yaml"
    with open(yaml_path, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def load_strategy(
    name: str, path: Path | str | None = None, overrides: Mapping | None = None
) -> StrategySpec:
    """Strategy `name` (S1..S4) with its validated parameters; `overrides` replaces some of
    them (used for the +/-20% robustness test)."""
    if name not in MODULES:
        raise KeyError(f"Unknown strategy {name!r}; known: {sorted(MODULES)}")
    module = MODULES[name]
    raw = {**load_params(path)[name], **(overrides or {})}
    params = module.Params(**raw)
    return StrategySpec(
        name=name,
        title=module.TITLE,
        params=params,
        signals=partial(module.signals, params=params),
        max_hold_bars=getattr(params, "max_hold_bars", None),
    )
