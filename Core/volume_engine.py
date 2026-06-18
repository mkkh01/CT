import pandas as pd
import numpy as np

class VolumeEngine:
    def __init__(self):
        pass

    def calculate_advanced_volume(self, df: pd.DataFrame):
        """حساب CVD, Delta, Relative Volume, و Volume Imbalance"""
        df = df.copy()
        
        # Delta & CVD (Proxy)
        df['delta'] = np.where(df['close'] > df['open'], df['volume'], -df['volume'])
        df['cvd'] = df['delta'].cumsum()
        
        # Relative Volume (RVOL)
        avg_vol = df['volume'].rolling(window=20).mean()
        df['rvol'] = df['volume'] / avg_vol
        
        # Volume Spikes
        df['vol_spike'] = df['rvol'] > 2.0
        
        # Volume Imbalance
        df['vol_imbalance'] = False
        for i in range(1, len(df)):
            if abs(df['open'].iloc[i] - df['close'].iloc[i-1]) > 0 and df['vol_spike'].iloc[i]:
                df.at[df.index[i], 'vol_imbalance'] = True
                
        return df

    def get_order_flow_bias(self, df: pd.DataFrame):
        """تحليل تدفق الأوامر (Order Flow Bias)"""
        df = self.calculate_advanced_volume(df)
        last_cvd_slope = df['cvd'].iloc[-1] - df['cvd'].iloc[-5]
        
        bias = "NEUTRAL"
        if last_cvd_slope > 0 and df['close'].iloc[-1] > df['open'].iloc[-1]:
            bias = "AGGRESSIVE_BUYING"
        elif last_cvd_slope < 0 and df['close'].iloc[-1] < df['open'].iloc[-1]:
            bias = "AGGRESSIVE_SELLING"
            
        return {
            "bias": bias,
            "rvol": df['rvol'].iloc[-1],
            "cvd_trend": "UP" if last_cvd_slope > 0 else "DOWN"
        }
