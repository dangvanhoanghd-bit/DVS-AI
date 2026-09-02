"""
STUB TẠM THỜI cho pandas_ta — CHỈ dùng để kiểm thử logic DVS AI Alpha 1.0
khi sandbox không có mạng để cài thư viện thật. Dùng đúng công thức chuẩn
(Wilder's smoothing cho RSI/ADX/ATR) nên kết quả tương đương thư viện thật.

KHÔNG dùng file này khi chạy ứng dụng thật — hãy `pip install pandas_ta`
theo đúng requirements.txt.
"""
from __future__ import annotations

import pandas as pd
import numpy as np


def cmf(high, low, close, volume, length=20):
    high_low_range = (high - low).replace(0, np.nan)
    mfm = ((close - low) - (high - close)) / high_low_range
    mfm = mfm.fillna(0.0)
    mfv = mfm * volume
    return mfv.rolling(window=length, min_periods=length).sum() / \
        volume.rolling(window=length, min_periods=length).sum()


def rsi(close, length=14):
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / length, min_periods=length, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / length, min_periods=length, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    result = 100 - (100 / (1 + rs))
    result = result.where(avg_loss != 0, 100.0)
    return result


def ema(close, length=20):
    return close.ewm(span=length, adjust=False, min_periods=length).mean()


def _true_range(high, low, close):
    prev_close = close.shift(1)
    tr1 = high - low
    tr2 = (high - prev_close).abs()
    tr3 = (low - prev_close).abs()
    return pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)


def atr(high, low, close, length=14):
    tr = _true_range(high, low, close)
    return tr.ewm(alpha=1 / length, min_periods=length, adjust=False).mean()


def adx(high, low, close, length=14):
    up_move = high.diff()
    down_move = -low.diff()

    plus_dm = pd.Series(
        np.where((up_move > down_move) & (up_move > 0), up_move, 0.0), index=high.index
    )
    minus_dm = pd.Series(
        np.where((down_move > up_move) & (down_move > 0), down_move, 0.0), index=high.index
    )

    tr = _true_range(high, low, close)
    smoothed_tr = tr.ewm(alpha=1 / length, min_periods=length, adjust=False).mean()
    smoothed_plus_dm = plus_dm.ewm(alpha=1 / length, min_periods=length, adjust=False).mean()
    smoothed_minus_dm = minus_dm.ewm(alpha=1 / length, min_periods=length, adjust=False).mean()

    plus_di = 100 * smoothed_plus_dm / smoothed_tr.replace(0, np.nan)
    minus_di = 100 * smoothed_minus_dm / smoothed_tr.replace(0, np.nan)

    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    adx_val = dx.ewm(alpha=1 / length, min_periods=length, adjust=False).mean()

    return pd.DataFrame({
        f"ADX_{length}": adx_val,
        f"DMP_{length}": plus_di,
        f"DMN_{length}": minus_di,
    })
