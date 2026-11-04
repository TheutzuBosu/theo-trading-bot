"""Intraday 5-minute Opening Range Breakout strategy D2 (Zarattini & Aziz 2023, D29 benchmark).

Pure function operating on 1-minute session bars in New York time and returning a DataFrame with
`SIGNAL_COLUMNS` + `entry_reason` for `src/backtest/intraday_engine.py`.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class D2Params:
    """Parameters for D2 5-minute ORB (Zarattini & Aziz 2023, D29)."""

    orb_minutes: int = 5  # 09:30..09:34 inclusive -> signal on 09:34 bar, fill at 09:35 Open
    doji_threshold: float = 1e-4  # |Close - Open| <= 0.01% of Open -> no trade
    target_r: float = 10.0  # 10R profit target; otherwise hold to session close
    max_symbol_size: float = 0.5  # 50% of capital per symbol (capped at 0.5% risk in engine)


def generate_d2_signals(
    df: pd.DataFrame,
    params: D2Params | None = None,
) -> pd.DataFrame:
    """Generate 5-minute ORB signals (D29)."""
    p = params or D2Params()
    idx = df.index
    n = len(df)

    entry = np.zeros(n, dtype=np.int8)
    stop = np.full(n, np.nan, dtype=float)
    target = np.full(n, np.nan, dtype=float)
    size_arr = np.full(n, np.nan, dtype=float)
    reasons = np.full(n, "", dtype=object)

    if n == 0:
        return pd.DataFrame(
            {
                "entry": entry,
                "stop": stop,
                "target": target,
                "size": size_arr,
                "exit": np.zeros(n, dtype=bool),
                "exit_long": np.zeros(n, dtype=bool),
                "exit_short": np.zeros(n, dtype=bool),
                "stop_long": np.full(n, np.nan, dtype=float),
                "stop_short": np.full(n, np.nan, dtype=float),
                "stop_after_target": np.full(n, np.nan, dtype=float),
                "entry_reason": reasons,
            },
            index=idx,
        )

    days = pd.DatetimeIndex(idx.tz_localize(None).normalize())
    mins = np.asarray(idx.hour * 60 + idx.minute, dtype=int)
    starts = np.flatnonzero(np.r_[True, days[1:] != days[:-1]])
    ends = np.r_[starts[1:], n]

    o = df["open"].to_numpy(dtype=float)
    h = df["high"].to_numpy(dtype=float)
    lo = df["low"].to_numpy(dtype=float)
    c = df["close"].to_numpy(dtype=float)

    open_min = 9 * 60 + 30
    orb_end_min = open_min + p.orb_minutes - 1  # 09:34 -> 574

    for s, e in zip(starts, ends):
        n_day = e - s
        if n_day < p.orb_minutes:
            continue
        day_mins = mins[s:e]
        if day_mins[0] != open_min:
            continue
        # Find the bar at orb_end_min (09:34)
        pos = int(np.searchsorted(day_mins, orb_end_min, side="right")) - 1
        if pos <= 0 or not (day_mins[pos] == orb_end_min or (pos + 1) < n_day):
            continue
        sig_idx = s + pos
        or_open = o[s]
        or_close = c[sig_idx]
        or_high = float(np.max(h[s : sig_idx + 1]))
        or_low = float(np.min(lo[s : sig_idx + 1]))

        if abs(or_close - or_open) <= p.doji_threshold * or_open:
            continue

        if or_close > or_open:
            risk = or_close - or_low
            if risk <= 0:
                continue
            entry[sig_idx] = 1
            stop[sig_idx] = or_low
            target[sig_idx] = or_close + p.target_r * risk
            size_arr[sig_idx] = p.max_symbol_size
            reasons[sig_idx] = (
                f"D2 ORB{p.orb_minutes} long: Close={or_close:.2f} > Open={or_open:.2f}, "
                f"stop={or_low:.2f}, target={target[sig_idx]:.2f}"
            )
        elif or_close < or_open:
            risk = or_high - or_close
            if risk <= 0:
                continue
            entry[sig_idx] = -1
            stop[sig_idx] = or_high
            target[sig_idx] = or_close - p.target_r * risk
            size_arr[sig_idx] = p.max_symbol_size
            reasons[sig_idx] = (
                f"D2 ORB{p.orb_minutes} short: Close={or_close:.2f} < Open={or_open:.2f}, "
                f"stop={or_high:.2f}, target={target[sig_idx]:.2f}"
            )

    return pd.DataFrame(
        {
            "entry": entry,
            "stop": stop,
            "target": target,
            "size": size_arr,
            "exit": np.zeros(n, dtype=bool),
            "exit_long": np.zeros(n, dtype=bool),
            "exit_short": np.zeros(n, dtype=bool),
            "stop_long": np.full(n, np.nan, dtype=float),
            "stop_short": np.full(n, np.nan, dtype=float),
            "stop_after_target": np.full(n, np.nan, dtype=float),
            "entry_reason": reasons,
        },
        index=idx,
    )
