import pandas as pd
import numpy as np
import logging

logger = logging.getLogger(__name__)

class VolumeEngine:
    def __init__(self):
        pass

    def calculate_advanced_volume(self, df: pd.DataFrame):
        """حساب CVD, Delta, RVOL, و Volume Imbalance"""
        df = df.copy()
        
        # Delta & CVD
        if 'taker_buy_volume' in df.columns:
            df['taker_buy_vol'] = df['taker_buy_volume']
            df['taker_sell_vol'] = df['volume'] - df['taker_buy_volume']
            df['delta'] = df['taker_buy_vol'] - df['taker_sell_vol']
        else:
            logger.warning("⚠️ [VOLUME] 'taker_buy_volume' missing, falling back to candle-color delta.")
            df['delta'] = np.where(df['close'] > df['open'], df['volume'], -df['volume'])
            
        df['cvd'] = df['delta'].cumsum()
        
        # Relative Volume (RVOL)
        df['rvol'] = df['volume'] / df['volume'].rolling(window=20).mean()
        
        # Volume Imbalance
        df['vol_imbalance'] = (df['volume'] > df['volume'].shift(1) * 2) & (abs(df['close'] - df['open']) > abs(df['close'].shift(1) - df['open'].shift(1)))
        
        # Open Interest & Funding Rate (Proxy for Spot/Simulated)
        # In real HFT, these come from specific exchange APIs
        df['oi_proxy'] = df['volume'].rolling(window=10).sum()
        
        return df

    def get_volume_bias(self, df: pd.DataFrame):
        df = self.calculate_advanced_volume(df)
        last_cvd_change = df['cvd'].iloc[-1] - df['cvd'].iloc[-5]
        
        bias = "NEUTRAL"
        if last_cvd_change > 0 and df['rvol'].iloc[-1] > 1.2:
            bias = "AGGRESSIVE_BUYING"
        elif last_cvd_change < 0 and df['rvol'].iloc[-1] > 1.2:
            bias = "AGGRESSIVE_SELLING"
            
        return {
            "bias": bias,
            "rvol": df['rvol'].iloc[-1],
            "cvd_trend": "UP" if last_cvd_change > 0 else "DOWN",
            "imbalance": df['vol_imbalance'].iloc[-1]
        }
