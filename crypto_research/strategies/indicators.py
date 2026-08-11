from __future__ import annotations

import numpy as np
import pandas as pd


def add_indicators(frame: pd.DataFrame, params: dict | None = None) -> pd.DataFrame:
    p = {
        "fast_ema": 20, "slow_ema": 50, "rsi_period": 14,
        "atr_period": 14, "adx_period": 14, "volume_period": 20,
        "breakout_period": 20, "swing_period": 5,
    }
    if params:
        p.update(params)
    df = frame.copy().sort_values("timestamp").reset_index(drop=True)
    close, high, low, volume = df["close"], df["high"], df["low"], df["volume"]

    df["ema_fast"] = close.ewm(span=int(p["fast_ema"]), adjust=False, min_periods=int(p["fast_ema"])).mean()
    df["ema_slow"] = close.ewm(span=int(p["slow_ema"]), adjust=False, min_periods=int(p["slow_ema"])).mean()
    df["trend_filter"] = df["ema_fast"] > df["ema_slow"]
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / int(p["rsi_period"]), adjust=False, min_periods=int(p["rsi_period"])).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / int(p["rsi_period"]), adjust=False, min_periods=int(p["rsi_period"])).mean()
    rs = gain / loss.replace(0, np.nan)
    df["rsi"] = (100 - (100 / (1 + rs))).fillna(50.0)

    prev_close = close.shift(1)
    tr = pd.concat([high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1).max(axis=1)
    df["tr"] = tr
    df["atr"] = tr.ewm(alpha=1 / int(p["atr_period"]), adjust=False, min_periods=int(p["atr_period"])).mean()
    df["atr_pct"] = df["atr"] / close.replace(0, np.nan)

    up_move = high.diff()
    down_move = -low.diff()
    plus_dm = up_move.where((up_move > down_move) & (up_move > 0), 0.0)
    minus_dm = down_move.where((down_move > up_move) & (down_move > 0), 0.0)
    atr = df["atr"].replace(0, np.nan)
    plus_di = 100 * plus_dm.ewm(alpha=1 / int(p["adx_period"]), adjust=False).mean() / atr
    minus_di = 100 * minus_dm.ewm(alpha=1 / int(p["adx_period"]), adjust=False).mean() / atr
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    df["adx"] = dx.ewm(alpha=1 / int(p["adx_period"]), adjust=False).mean()

    df["volume_ma"] = volume.rolling(int(p["volume_period"]), min_periods=int(p["volume_period"])).mean()
    df["relative_volume"] = volume / df["volume_ma"].replace(0, np.nan)
    df["roc"] = close.pct_change(int(p["breakout_period"]))
    df["rolling_volatility"] = close.pct_change().rolling(int(p["volume_period"]), min_periods=int(p["volume_period"])).std()

    lookback = int(p["breakout_period"])
    df["previous_high"] = high.shift(1).rolling(lookback, min_periods=lookback).max()
    df["previous_low"] = low.shift(1).rolling(lookback, min_periods=lookback).min()
    df["breakout_up"] = close > df["previous_high"]
    df["pullback_to_fast"] = (low <= df["ema_fast"] * (1 + float(p.get("pullback_tolerance", 0.003)))) & (close > df["ema_fast"])

    swing = int(p["swing_period"])
    df["swing_low"] = low.shift(1).rolling(swing, min_periods=swing).min()
    df["swing_high"] = high.shift(1).rolling(swing, min_periods=swing).max()
    df["higher_high"] = high > df["swing_high"].shift(1)
    df["higher_low"] = low > df["swing_low"].shift(1)
    df["bullish_structure"] = df["higher_high"].rolling(3, min_periods=1).max().astype(bool) | df["higher_low"].rolling(3, min_periods=1).max().astype(bool)

    # All signals below use current/previous closed bars only; execution is next-bar open.
    df["bullish_candle"] = (close > df["open"]) & ((close - df["open"]) > (high - low) * 0.35)
    df["momentum_confirmed"] = (df["rsi"] >= 52) & (df["rsi"] <= 78) & (df["roc"] > 0)
    df["volume_confirmed"] = df["relative_volume"] >= float(p.get("relative_volume_threshold", 1.0))
    df["valid_features"] = df[["ema_fast", "ema_slow", "atr", "previous_high", "previous_low", "volume_ma"]].notna().all(axis=1)
    return df
