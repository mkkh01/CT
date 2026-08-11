from __future__ import annotations

import numpy as np
import pandas as pd


def classify_regimes(reference: pd.DataFrame, trend_window: int = 200, volatility_window: int = 30) -> pd.DataFrame:
    df = reference.sort_values("timestamp").copy()
    close = df["close"].astype(float)
    ema = close.ewm(span=trend_window, adjust=False, min_periods=trend_window).mean()
    ret = close.pct_change()
    vol = ret.rolling(volatility_window, min_periods=volatility_window).std()
    vol_median = vol.expanding(min_periods=volatility_window).median()
    direction = close / ema.replace(0, np.nan) - 1.0
    regime = np.select([direction > 0.03, direction < -0.03], ["bull", "bear"], default="sideways")
    vol_regime = np.where(vol > vol_median, "high_volatility", "low_volatility")
    out = pd.DataFrame({"timestamp": df["timestamp"], "regime": regime, "volatility_regime": vol_regime})
    return out


def label_trades(trades: pd.DataFrame, reference: pd.DataFrame) -> pd.DataFrame:
    if trades.empty:
        return trades.copy()
    labels = classify_regimes(reference)
    joined = pd.merge_asof(
        trades.sort_values("entry_timestamp"), labels.sort_values("timestamp"),
        left_on="entry_timestamp", right_on="timestamp", direction="backward",
    )
    return joined.drop(columns=["timestamp"], errors="ignore")


def regime_summary(trades: pd.DataFrame) -> pd.DataFrame:
    if trades.empty or "regime" not in trades.columns:
        return pd.DataFrame()
    rows = []
    for key, group in trades.groupby(["regime", "volatility_regime"], dropna=False):
        pnl = group["pnl"].astype(float)
        gross_profit = pnl[pnl > 0].sum()
        gross_loss = -pnl[pnl <= 0].sum()
        rows.append({"regime": key[0], "volatility_regime": key[1], "trades": len(group), "win_rate": (pnl > 0).mean(), "profit_factor": gross_profit / gross_loss if gross_loss else float("inf"), "net_profit": pnl.sum(), "expectancy": pnl.mean()})
    return pd.DataFrame(rows)
