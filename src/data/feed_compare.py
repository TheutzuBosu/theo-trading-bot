"""SIP vs IEX comparison for 1-minute bars (Faza B, B1, D23).

The demo (B6) reads IEX bars live while the backtest uses SIP. This measures how far apart the two
are on the per-minute close and on the session VWAP (anchored at 9:30), which D1 uses.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def session_vwap(df: pd.DataFrame) -> pd.Series:
    """Cumulative VWAP from the session open, per minute, from bar vwap and volume."""
    day = pd.Series(df.index.date, index=df.index)
    pv = (df["vwap"] * df["volume"]).groupby(day).cumsum()
    vol = df["volume"].groupby(day).cumsum()
    return pv / vol.replace(0, np.nan)


def _bps_stats(diff_bps: pd.Series) -> dict:
    a = diff_bps.abs().dropna()
    if a.empty:
        return {"n": 0}
    return {
        "n": int(len(a)),
        "median": round(float(a.median()), 3),
        "mean": round(float(a.mean()), 3),
        "p95": round(float(a.quantile(0.95)), 3),
        "p99": round(float(a.quantile(0.99)), 3),
        "max": round(float(a.max()), 3),
        "bias": round(float(diff_bps.dropna().mean()), 3),
    }


def compare_feeds(sip: pd.DataFrame, iex: pd.DataFrame) -> dict:
    """Compare IEX against SIP on the overlapping days. Differences in basis points (IEX - SIP).

    - coverage: share of SIP minutes that also exist in IEX
    - volume_share: IEX volume / SIP volume on common minutes
    - close_bps: per-minute close difference on common minutes
    - vwap_bps: session VWAP difference per SIP minute (IEX VWAP carried forward over its gaps)
    - vwap_bps_after_30min: same, from 10:00 ET on (the first minutes are the noisiest)
    """
    days = sorted(set(sip.index.date) & set(iex.index.date))
    if not days:
        raise ValueError("no overlapping days between SIP and IEX")
    sip = sip[pd.Index(sip.index.date).isin(days)]
    iex = iex[pd.Index(iex.index.date).isin(days)]
    common = sip.index.intersection(iex.index)

    close_bps = (iex.loc[common, "close"] / sip.loc[common, "close"] - 1.0) * 1e4

    v_sip = session_vwap(sip)
    v_iex = session_vwap(iex).reindex(sip.index)
    v_iex = v_iex.groupby(pd.Series(sip.index.date, index=sip.index)).ffill()
    vwap_bps = (v_iex / v_sip - 1.0) * 1e4
    late = sip.index.time >= pd.Timestamp("10:00").time()

    return {
        "days": len(days),
        "first_day": days[0].isoformat(),
        "last_day": days[-1].isoformat(),
        "coverage": round(len(common) / len(sip), 4),
        "volume_share": round(
            float(iex.loc[common, "volume"].sum() / sip.loc[common, "volume"].sum()), 4
        ),
        "close_bps": _bps_stats(close_bps),
        "vwap_bps": _bps_stats(vwap_bps),
        "vwap_bps_after_30min": _bps_stats(vwap_bps[late]),
    }
