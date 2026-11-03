"""Indicator tests against values calculated by hand (computations in the comments)."""

import numpy as np
import pandas as pd
import pytest

from src import indicators as ind


def _series(values):
    return pd.Series(values, index=pd.date_range("2026-01-05", periods=len(values), freq="B"))


def _ohlc(rows):
    df = pd.DataFrame(rows, columns=["high", "low", "close"])
    df.index = pd.date_range("2026-01-05", periods=len(df), freq="B")
    return df


def test_sma():
    out = ind.sma(_series([1.0, 2.0, 3.0, 4.0, 5.0]), 3)
    assert out.iloc[:2].isna().all()
    assert out.iloc[2:].tolist() == [2.0, 3.0, 4.0]


def test_ema_seeded_with_sma():
    # alpha = 2/(3+1) = 0.5; seed = (2+4+6)/3 = 4; then 0.5*8 + 0.5*4 = 6; 0.5*4 + 0.5*6 = 5
    out = ind.ema(_series([2.0, 4.0, 6.0, 8.0, 4.0]), 3)
    assert out.iloc[:2].isna().all()
    assert out.iloc[2:].tolist() == pytest.approx([4.0, 6.0, 5.0])


def test_true_range_and_atr():
    df = _ohlc(
        [
            [10.0, 8.0, 9.0],  # TR = 10-8 = 2 (no previous close)
            [11.0, 9.0, 10.5],  # max(2, |11-9|, |9-9|) = 2
            [13.0, 10.0, 12.0],  # max(3, 2.5, 0.5) = 3
            [12.5, 11.0, 11.5],  # max(1.5, 0.5, 1) = 1.5
            [15.0, 14.0, 14.5],  # gap: max(1, 3.5, 2.5) = 3.5
        ]
    )
    assert ind.true_range(df).tolist() == pytest.approx([2.0, 2.0, 3.0, 1.5, 3.5])
    # ATR(3): seed (2+2+3)/3 = 7/3; (2*7/3 + 1.5)/3 = 37/18; (2*37/18 + 3.5)/3 = 137/54
    out = ind.atr(df, 3)
    assert out.iloc[:2].isna().all()
    assert out.iloc[2:].tolist() == pytest.approx([7 / 3, 37 / 18, 137 / 54])


def test_atr_default_period_is_20():
    df = _ohlc([[11.0, 9.0, 10.0]] * 25)
    out = ind.atr(df)
    assert out.iloc[:19].isna().all()
    assert out.iloc[19] == pytest.approx(2.0)


def test_rsi_2_by_hand():
    # deltas: +1, -0.5, +1, -0.5
    # seed: gain (1+0)/2 = 0.5, loss (0+0.5)/2 = 0.25 -> RS 2 -> 66.667
    # next: gain (0.5+1)/2 = 0.75, loss (0.25+0)/2 = 0.125 -> RS 6 -> 85.714
    # next: gain (0.75+0)/2 = 0.375, loss (0.125+0.5)/2 = 0.3125 -> RS 1.2 -> 54.545
    out = ind.rsi(_series([10.0, 11.0, 10.5, 11.5, 11.0]), 2)
    assert out.iloc[:2].isna().all()
    assert out.iloc[2:].tolist() == pytest.approx([200 / 3, 600 / 7, 100 - 100 / 2.2])


def test_rsi_edge_cases():
    rising = ind.rsi(_series([1.0, 2.0, 3.0, 4.0, 5.0]), 2)
    assert rising.iloc[2:].tolist() == [100.0, 100.0, 100.0]
    flat = ind.rsi(_series([5.0] * 5), 2)
    assert flat.iloc[2:].tolist() == [50.0, 50.0, 50.0]
    # RSI(14) needs 14 deltas -> first value at bar 14
    assert (
        ind.rsi(_series(np.arange(1.0, 21.0))).first_valid_index()
        == _series(np.arange(1.0, 21.0)).index[14]
    )


def test_donchian_excludes_current_bar():
    highs = _series([1.0, 5.0, 3.0, 4.0, 2.0, 6.0])
    out = ind.donchian_high(highs, 3)
    # bar 5: max of bars 2..4 = 4, so the high of 6 on bar 5 is a breakout
    assert out.iloc[:3].isna().all()
    assert out.iloc[3:].tolist() == [5.0, 5.0, 4.0]
    lows = _series([5.0, 1.0, 3.0, 2.0, 4.0, 0.5])
    assert ind.donchian_low(lows, 3).iloc[3:].tolist() == [1.0, 1.0, 2.0]


def test_adx_by_hand():
    df = _ohlc(
        [
            [10.0, 9.0, 9.5],
            [11.0, 9.5, 10.5],  # +DM 1, -DM 0
            [11.5, 10.0, 10.2],  # +DM 0.5, -DM 0
            [10.8, 9.0, 9.2],  # +DM 0, -DM 1
            [10.0, 8.5, 9.8],  # +DM 0, -DM 0.5
            [11.0, 9.6, 10.8],  # +DM 1, -DM 0
        ]
    )
    # Wilder(2) of DM from bar 1: +DM 0.75, 0.375, 0.1875, 0.59375; -DM 0, 0.5, 0.5, 0.25
    # DX = 100*|+DM-(-DM)|/(+DM+(-DM)) (TR cancels): 100, 100/7, 500/11, 1100/27
    # ADX: seed (100 + 100/7)/2 = 400/7; (400/7 + 500/11)/2; (prev + 1100/27)/2
    adx_3 = 400 / 7
    adx_4 = (adx_3 + 500 / 11) / 2
    adx_5 = (adx_4 + 1100 / 27) / 2
    out = ind.adx(df, 2)
    assert out.iloc[:3].isna().all()
    assert out.iloc[3:].tolist() == pytest.approx([adx_3, adx_4, adx_5])


def test_momentum_12_1():
    close = _series(np.arange(1.0, 11.0))
    out = ind.momentum_12_1(close, lookback=5, skip=1)
    # bar 5: close[4] / close[0] - 1 = 5/1 - 1
    assert out.iloc[:5].isna().all()
    assert out.iloc[5] == pytest.approx(4.0)
    long = _series(np.arange(1.0, 301.0))
    default = ind.momentum_12_1(long)
    assert np.isnan(default.iloc[251])
    assert default.iloc[252] == pytest.approx(long.iloc[231] / long.iloc[0] - 1)


def test_macd_by_hand():
    # close 1, 2, 4, 3, 5, 6 with fast 2 (alpha 2/3), slow 3 (alpha 1/2), signal 2
    # EMA2: 3/2, 19/6, 55/18, 235/54, 883/162   EMA3: 7/3, 8/3, 23/6, 59/12
    # MACD (from bar 2): 5/6, 7/18, 14/27, 173/324
    # signal: seed (5/6 + 7/18)/2 = 11/18; then 89/162; then 131/243
    out = ind.macd(_series([1.0, 2.0, 4.0, 3.0, 5.0, 6.0]), fast=2, slow=3, signal=2)
    assert out["macd"].iloc[:2].isna().all()
    assert out["macd"].iloc[2:].tolist() == pytest.approx([5 / 6, 7 / 18, 14 / 27, 173 / 324])
    assert out["signal"].iloc[:3].isna().all()
    assert out["signal"].iloc[3:].tolist() == pytest.approx([11 / 18, 89 / 162, 131 / 243])
    assert out["hist"].iloc[3:].tolist() == pytest.approx(
        [7 / 18 - 11 / 18, 14 / 27 - 89 / 162, 173 / 324 - 131 / 243]
    )


def test_macd_default_periods():
    out = ind.macd(_series(np.arange(1.0, 61.0)))
    # MACD needs EMA26 (bar 25); the signal needs 9 MACD values (bar 33)
    assert out["macd"].first_valid_index() == out.index[25]
    assert out["signal"].first_valid_index() == out.index[33]
