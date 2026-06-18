import pandas as pd
import numpy as np
import aiohttp

class MarketContext:
    def __init__(self):
        self.base_url = "https://api.binance.com/api/v3"

    def calculate_vwap(self, df: pd.DataFrame):
        """حساب VWAP (Volume Weighted Average Price)"""
        v = df['volume'].values
        p = (df['high'] + df['low'] + df['close']).values / 3
        return (p * v).cumsum() / v.cumsum()

    def calculate_anchored_vwap(self, df: pd.DataFrame, anchor_idx):
        """حساب Anchored VWAP من نقطة محددة (مثل بداية الجلسة أو قمة/قاع رئيسي)"""
        if anchor_idx >= len(df): anchor_idx = 0
        df_sub = df.iloc[anchor_idx:]
        v = df_sub['volume'].values
        p = (df_sub['high'] + df_sub['low'] + df_sub['close']).values / 3
        avwap = (p * v).cumsum() / v.cumsum()
        return pd.Series(avwap, index=df_sub.index)

    def get_trend_strength(self, df: pd.DataFrame):
        """حساب قوة الاتجاه (Trend Strength) باستخدام ADX تقريبي أو Slope"""
        df = df.copy()
        df['ema_fast'] = df['close'].ewm(span=12).mean()
        df['ema_slow'] = df['close'].ewm(span=26).mean()
        slope = (df['ema_fast'].iloc[-1] - df['ema_fast'].iloc[-5]) / df['ema_fast'].iloc[-5]
        
        strength = abs(slope) * 1000
        return "STRONG" if strength > 5 else "WEAK"

    async def get_global_market_data(self):
        """جلب بيانات السوق العالمي (BTC, Dominance - Proxy)"""
        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(f"{self.base_url}/ticker/24hr?symbol=BTCUSDT") as resp:
                    btc_data = await resp.json()
                    btc_change = float(btc_data['priceChangePercent'])
                    return {
                        "btc_bias": "BULLISH" if btc_change > 0 else "BEARISH",
                        "market_regime": "TRENDING" if abs(btc_change) > 2 else "RANGING"
                    }
            except:
                return {"btc_bias": "NEUTRAL", "market_regime": "UNKNOWN"}
