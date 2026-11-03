"""Intraday momentum strategies D1 (Zarattini, Aziz & Barbon 2024) and D1b (Maróy 2025, D29/D29b).

Pure functions operating on 1-minute session bars in New York time and returning a DataFrame with
`SIGNAL_COLUMNS` + `entry_reason` for `src/backtest/intraday_engine.py`.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from src.data.intraday import nyse_sessions


@dataclass(frozen=True)
class D1Params:
    """Parameters for D1 (Zarattini et al. 2024, D29)."""

    lookback: int = 14
    mult: float = 1.0
    vol_lookback: int = 14
    sigma_target: float = 0.02
    max_symbol_size: float = 0.5
    first_check_min: int = 29  # 09:30 + 29m = 09:59 bar close (10:00 Open fill)
    check_freq_min: int = 30  # 09:59, 10:29, ..., 15:29
    no_entry_last_min: int = 30  # last check at 15:29 (12:29 on 13:00 early closes)


@dataclass(frozen=True)
class D1bParams:
    """Parameters for D1b ('VWAP & Ladder #1', Maróy 2025 Table 11, D29b)."""

    lookback: int = 4
    mult: float = 1.33
    sigma_target: float = 0.025
    max_symbol_size: float = 0.5
    first_check_min: int = 41  # 09:30 + 41m = 10:11 bar close (42 min after open)
    check_freq_min: int = 46  # 10:11, 10:57, 11:43, 12:29, 13:15, 14:01, 14:47
    exit_before_close_min: int = 30  # signal exit on 15:29 bar -> fills at 15:30 Open
    stop_0: float = -0.41  # in multiples of r
    stop_1: float = -0.28  # in multiples of r (applied after take_profit_0)
    take_profit_0: float = 2.2  # in multiples of r (50% partial exit)


def _session_vwap(df: pd.DataFrame, session_day: pd.Series) -> pd.Series:
    """Cumulative session VWAP from 09:30 ET using bar `vwap * volume` (or `close * volume`)."""
    price = df["vwap"] if "vwap" in df.columns else df["close"]
    vol = df["volume"].to_numpy(dtype=float)
    pv = price.to_numpy(dtype=float) * vol
    day_codes = session_day.to_numpy()
    starts = np.flatnonzero(np.r_[True, day_codes[1:] != day_codes[:-1]])
    ends = np.r_[starts[1:], len(df)]
    out = np.empty(len(df), dtype=float)
    c_arr = df["close"].to_numpy(dtype=float)
    for s, e in zip(starts, ends):
        cum_pv = np.cumsum(pv[s:e])
        cum_vol = np.cumsum(vol[s:e])
        with np.errstate(divide="ignore", invalid="ignore"):
            v = np.where(cum_vol > 0, cum_pv / cum_vol, c_arr[s:e])
        out[s:e] = v
    return pd.Series(out, index=df.index, name="session_vwap")


def compute_noise_bands(
    df: pd.DataFrame,
    lookback: int = 14,
    mult: float = 1.0,
) -> pd.DataFrame:
    """Compute Noise Area Upper Bound (UB), Lower Bound (LB), and minute sigma (D29).

    For session d and minute-of-day m:
      sigma(d, m) = mean_{d' in last L sessions < d} |Close(d', m) / Open_9:30(d') - 1|
      requiring at least max(1, L - 1) prior sessions with minute m.
      UB(d, m) = max(Open_9:30(d), Close_prev(d)) * (1 + mult * sigma(d, m))
      LB(d, m) = min(Open_9:30(d), Close_prev(d)) * (1 - mult * sigma(d, m))
    """
    if df.empty:
        return pd.DataFrame(columns=["sigma", "ub", "lb"], index=df.index, dtype=float)

    idx = df.index
    days = pd.Series(idx.tz_localize(None).normalize(), index=idx)
    minutes = pd.Series(idx.hour * 60 + idx.minute, index=idx)

    # Session open (first bar of each session) and previous session close
    session_open = df["open"].groupby(days).first()
    session_close = df["close"].groupby(days).last()
    prev_close = session_close.shift(1)

    open_per_bar = days.map(session_open).to_numpy(dtype=float)
    abs_move = np.abs(df["close"].to_numpy(dtype=float) / open_per_bar - 1.0)

    move_df = pd.DataFrame({"day": days.to_numpy(), "minute": minutes.to_numpy(), "move": abs_move})
    piv = move_df.pivot_table(index="day", columns="minute", values="move", aggfunc="last")
    all_mins = pd.Index(range(9 * 60 + 30, 16 * 60), name="minute")
    piv = piv.reindex(columns=all_mins)
    min_p = max(1, lookback - 1)
    sigma_piv = piv.shift(1).rolling(window=lookback, min_periods=min_p).mean()

    # Map (day, minute) back to bar index
    day_idx = sigma_piv.index.get_indexer(days.to_numpy())
    min_idx = sigma_piv.columns.get_indexer(minutes.to_numpy())
    sigma_vals = sigma_piv.to_numpy(dtype=float)[day_idx, min_idx]

    prev_c_per_bar = days.map(prev_close).to_numpy(dtype=float)
    # On the first day prev_close is NaN; use session open as reference (sigma is NaN anyway)
    upper_ref = np.where(
        np.isfinite(prev_c_per_bar), np.maximum(open_per_bar, prev_c_per_bar), open_per_bar
    )
    lower_ref = np.where(
        np.isfinite(prev_c_per_bar), np.minimum(open_per_bar, prev_c_per_bar), open_per_bar
    )

    ub = upper_ref * (1.0 + mult * sigma_vals)
    lb = lower_ref * (1.0 - mult * sigma_vals)
    return pd.DataFrame({"sigma": sigma_vals, "ub": ub, "lb": lb}, index=idx)


def _daily_volatility(
    df: pd.DataFrame,
    days: pd.Series,
    vol_lookback: int,
    ddof: int = 1,
) -> np.ndarray:
    """Rolling std of the last `vol_lookback` daily close-to-close returns up to yesterday."""
    session_close = df["close"].groupby(days).last()
    ret = session_close.pct_change()
    sig_d = ret.shift(1).rolling(window=vol_lookback, min_periods=vol_lookback).std(ddof=ddof)
    return days.map(sig_d).to_numpy(dtype=float)


def _session_close_minutes(days_unique: pd.DatetimeIndex) -> dict[pd.Timestamp, int]:
    """Return planned session close in minutes from midnight (960 for 16:00, 780 for 13:00)."""
    start_d = days_unique.min().date()
    end_d = days_unique.max().date()
    try:
        sched = nyse_sessions(start_d, end_d)
    except Exception:  # noqa: BLE001
        sched = pd.DataFrame()
    out: dict[pd.Timestamp, int] = {}
    for d in days_unique:
        if not sched.empty and d in sched.index:
            c_ts = sched.loc[d, "close"]
            out[d] = int(c_ts.hour * 60 + c_ts.minute)
        else:
            out[d] = 16 * 60
    return out


def _select_check_and_exit_bars(
    idx: pd.DatetimeIndex,
    first_check_min: int,
    check_freq_min: int,
    no_entry_last_min: int,
    time_exit_before_close_min: int | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """Identify check bars (including fallback to last closed bar if a check minute is missing, D26)
    and optional time-exit bars (for D1b: 15:29 / 12:29).
    """
    n = len(idx)
    is_check = np.zeros(n, dtype=bool)
    is_time_exit = np.zeros(n, dtype=bool)
    if n == 0:
        return is_check, is_time_exit

    days = pd.DatetimeIndex(idx.tz_localize(None).normalize())
    mins = np.asarray(idx.hour * 60 + idx.minute, dtype=int)
    starts = np.flatnonzero(np.r_[True, days[1:] != days[:-1]])
    ends = np.r_[starts[1:], n]
    close_map = _session_close_minutes(pd.DatetimeIndex(days[starts]))

    for s, e in zip(starts, ends):
        if e - s < 1:
            continue
        d = days[s]
        c_min = close_map.get(d, 16 * 60)
        open_min = 9 * 60 + 30
        day_mins = mins[s:e]
        n_day = e - s

        exit_cutoff_min = c_min - no_entry_last_min - 1  # 15:29 for D1 (960 - 30 - 1 = 929)
        if time_exit_before_close_min is not None:
            # D1b exits at Open of 15:30 (12:30), so signal exit on 15:29 (12:29) bar
            target_exit_min = c_min - time_exit_before_close_min - 1
            pos = int(np.searchsorted(day_mins, target_exit_min, side="right")) - 1
            if pos >= 0 and (day_mins[pos] == target_exit_min or (pos + 1) < n_day):
                is_time_exit[s + pos] = True
            # No entries at or after the time-exit bar
            exit_cutoff_min = min(exit_cutoff_min, target_exit_min - 1)

        prev_pos = -1
        t_min = open_min + first_check_min
        while t_min <= exit_cutoff_min:
            pos = int(np.searchsorted(day_mins, t_min, side="right")) - 1
            if pos > prev_pos and (day_mins[pos] == t_min or (pos + 1) < n_day):
                is_check[s + pos] = True
                prev_pos = pos
            t_min += check_freq_min

    return is_check, is_time_exit


def generate_d1_signals(
    df: pd.DataFrame,
    params: D1Params | None = None,
) -> pd.DataFrame:
    """Generate D1 Noise Area momentum signals (Zarattini, Aziz & Barbon 2024, D29)."""
    p = params or D1Params()
    idx = df.index
    n = len(df)
    days = pd.Series(idx.tz_localize(None).normalize(), index=idx)

    bands = compute_noise_bands(df, lookback=p.lookback, mult=p.mult)
    vwap = _session_vwap(df, days).to_numpy(dtype=float)
    sigma_d = _daily_volatility(df, days, vol_lookback=p.vol_lookback, ddof=1)
    is_check, _ = _select_check_and_exit_bars(
        idx,
        first_check_min=p.first_check_min,
        check_freq_min=p.check_freq_min,
        no_entry_last_min=p.no_entry_last_min,
        time_exit_before_close_min=None,
    )

    c = df["close"].to_numpy(dtype=float)
    ub = bands["ub"].to_numpy(dtype=float)
    lb = bands["lb"].to_numpy(dtype=float)
    valid = is_check & np.isfinite(ub) & np.isfinite(lb) & np.isfinite(vwap)

    long_cond = valid & (c > ub) & (c > vwap)
    short_cond = valid & (c < lb) & (c < vwap)

    entry = np.zeros(n, dtype=np.int8)
    entry[long_cond] = 1
    entry[short_cond] = -1

    # Initial stop at broker is the opposite band LB (for long) or UB (for short) (D29)
    stop = np.full(n, np.nan, dtype=float)
    stop[long_cond] = lb[long_cond]
    stop[short_cond] = ub[short_cond]

    # Trailing exit at check bars when Close <= max(UB, VWAP) (long) or >= min(LB, VWAP) (short)
    exit_long = valid & (c <= np.maximum(ub, vwap))
    exit_short = valid & (c >= np.minimum(lb, vwap))

    with np.errstate(divide="ignore", invalid="ignore"):
        lev = np.where(
            np.isfinite(sigma_d) & (sigma_d > 0), np.minimum(1.0, p.sigma_target / sigma_d), 1.0
        )
    size_arr = np.where(entry != 0, p.max_symbol_size * lev, np.nan)

    reasons = np.full(n, "", dtype=object)
    for i in np.flatnonzero(entry != 0):
        side = "long" if entry[i] == 1 else "short"
        band_val = ub[i] if entry[i] == 1 else lb[i]
        cmp_op = ">" if entry[i] == 1 else "<"
        reasons[i] = (
            f"D1(L={p.lookback},m={p.mult}) {side}: Close={c[i]:.2f} {cmp_op} "
            f"band={band_val:.2f} & VWAP={vwap[i]:.2f}"
        )

    return pd.DataFrame(
        {
            "entry": entry,
            "stop": stop,
            "target": np.full(n, np.nan, dtype=float),
            "size": size_arr,
            "exit": np.zeros(n, dtype=bool),
            "exit_long": exit_long,
            "exit_short": exit_short,
            "stop_long": np.full(n, np.nan, dtype=float),
            "stop_short": np.full(n, np.nan, dtype=float),
            "stop_after_target": np.full(n, np.nan, dtype=float),
            "entry_reason": reasons,
        },
        index=idx,
    )


def generate_d1b_signals(
    df: pd.DataFrame,
    params: D1bParams | None = None,
) -> pd.DataFrame:
    """Generate D1b 'VWAP & Ladder #1' signals (Maróy 2025, D29b)."""
    p = params or D1bParams()
    idx = df.index
    n = len(df)
    days = pd.Series(idx.tz_localize(None).normalize(), index=idx)

    bands = compute_noise_bands(df, lookback=p.lookback, mult=p.mult)
    vwap = _session_vwap(df, days).to_numpy(dtype=float)
    # Maróy eq. 4 uses 1/L (ddof=0) over the last L daily returns
    sigma_d = _daily_volatility(df, days, vol_lookback=p.lookback, ddof=0)
    is_check, is_time_exit = _select_check_and_exit_bars(
        idx,
        first_check_min=p.first_check_min,
        check_freq_min=p.check_freq_min,
        no_entry_last_min=p.exit_before_close_min,
        time_exit_before_close_min=p.exit_before_close_min,
    )

    c = df["close"].to_numpy(dtype=float)
    ub = bands["ub"].to_numpy(dtype=float)
    lb = bands["lb"].to_numpy(dtype=float)
    valid = is_check & np.isfinite(ub) & np.isfinite(lb) & np.isfinite(vwap)

    long_cond = valid & (c > ub) & (c > vwap)
    short_cond = valid & (c < lb) & (c < vwap)

    entry = np.zeros(n, dtype=np.int8)
    entry[long_cond] = 1
    entry[short_cond] = -1

    with np.errstate(divide="ignore", invalid="ignore"):
        lev = np.where(
            np.isfinite(sigma_d) & (sigma_d > 0), np.minimum(1.0, p.sigma_target / sigma_d), 1.0
        )
        # Maróy ladder unit r in dollars per share: Close * 0.005 / min(1, sigma_target / sigma)
        r_unit = c * 0.005 / lev

    stop_0_dist = abs(p.stop_0) * r_unit
    stop_1_dist = abs(p.stop_1) * r_unit
    tp_0_dist = abs(p.take_profit_0) * r_unit

    stop = np.full(n, np.nan, dtype=float)
    stop_after_target = np.full(n, np.nan, dtype=float)
    target = np.full(n, np.nan, dtype=float)

    # Long: initial stop = max(Close - |stop_0|*r, VWAP); after partial target = Close - |stop_1|*r
    stop[long_cond] = np.maximum(c[long_cond] - stop_0_dist[long_cond], vwap[long_cond])
    stop_after_target[long_cond] = np.maximum(
        c[long_cond] - stop_1_dist[long_cond], vwap[long_cond]
    )
    target[long_cond] = c[long_cond] + tp_0_dist[long_cond]

    # Short: initial stop = min(Close + |stop_0|*r, VWAP); after partial target = Close + |stop_1|*r
    stop[short_cond] = np.minimum(c[short_cond] + stop_0_dist[short_cond], vwap[short_cond])
    stop_after_target[short_cond] = np.minimum(
        c[short_cond] + stop_1_dist[short_cond], vwap[short_cond]
    )
    target[short_cond] = c[short_cond] - tp_0_dist[short_cond]

    size_arr = np.where(entry != 0, p.max_symbol_size * lev, np.nan)

    reasons = np.full(n, "", dtype=object)
    for i in np.flatnonzero(entry != 0):
        side = "long" if entry[i] == 1 else "short"
        band_val = ub[i] if entry[i] == 1 else lb[i]
        reasons[i] = (
            f"D1b {side}: Close={c[i]:.2f}, band={band_val:.2f}, "
            f"VWAP={vwap[i]:.2f}, tp0={target[i]:.2f}"
        )

    # Trailing stop updated every minute to session VWAP (tightens only in engine)
    return pd.DataFrame(
        {
            "entry": entry,
            "stop": stop,
            "target": target,
            "size": size_arr,
            "exit": is_time_exit,
            "exit_long": np.zeros(n, dtype=bool),
            "exit_short": np.zeros(n, dtype=bool),
            "stop_long": vwap.copy(),
            "stop_short": vwap.copy(),
            "stop_after_target": stop_after_target,
            "entry_reason": reasons,
        },
        index=idx,
    )
