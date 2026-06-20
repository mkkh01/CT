import pandas as pd
import numpy as np
import aiohttp
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

class MarketContext:
    def __init__(self):
        self.base_url = "https://api.binance.com/api/v3"

    def calculate_vwap(self, df: pd.DataFrame):
        v = df['volume'].values
        p = (df['high'] + df['low'] + df['close']).values / 3
        return (p * v).cumsum() / v.cumsum()

    def calculate_anchored_vwap(self, df: pd.DataFrame, anchor_idx=0):
        df_sub = df.iloc[anchor_idx:]
        v = df_sub['volume'].values
        p = (df_sub['high'] + df_sub['low'] + df_sub['close']).values / 3
        avwap = (p * v).cumsum() / v.cumsum()
        return pd.Series(avwap, index=df_sub.index)

    def detect_market_regime(self, df: pd.DataFrame):
        """تحديد حالة السوق (Trending, Ranging, Volatile)"""
        returns = df['close'].pct_change().dropna()
        volatility = returns.std() * np.sqrt(252) # Annualized volatility proxy
        
        # Simple regime detection
        ema_fast = df['close'].ewm(span=20).mean()
        ema_slow = df['close'].ewm(span=50).mean()
        
        if volatility > 0.05: return "VOLATILE"
        if ema_fast.iloc[-1] > ema_slow.iloc[-1] * 1.02: return "TRENDING_UP"
        if ema_fast.iloc[-1] < ema_slow.iloc[-1] * 0.98: return "TRENDING_DOWN"
        return "RANGING"

    async def get_market_correlations(self):
        """تحليل الارتباط مع BTC, ETH, Dominance"""
        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(f"{self.base_url}/ticker/24hr?symbols=[\"BTCUSDT\",\"ETHUSDT\"]") as resp:
                    data = await resp.json()
                    btc_change = float(data[0]['priceChangePercent'])
                    return {
                        "btc_bias": "BULLISH" if btc_change > 0.5 else "BEARISH" if btc_change < -0.5 else "NEUTRAL",
                        "market_strength": "STRONG" if abs(btc_change) > 2 else "NORMAL"
                    }
            except:
                return {"btc_bias": "NEUTRAL", "market_strength": "UNKNOWN"}
