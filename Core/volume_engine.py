import pandas as pd
import numpy as np

class VolumeEngine:
    def __init__(self):
        pass

    def calculate_delta(self, df: pd.DataFrame):
        """حساب دلتا الحجم (Volume Delta) بشكل تقريبي بناءً على حركة السعر"""
        # في بيئة Spot وبدون بيانات Order Flow حقيقية، نستخدم طريقة "Tick Rule" أو "Proxy Delta"
        df = df.copy()
        df['delta'] = np.where(df['close'] > df['open'], df['volume'], -df['volume'])
        df['cvd'] = df['delta'].cumsum() # Cumulative Volume Delta
        return df

    def detect_volume_spikes(self, df: pd.DataFrame, threshold=2.0):
        """كشف طفرات الحجم (Volume Spikes)"""
        avg_vol = df['volume'].rolling(window=20).mean()
        df['vol_spike'] = df['volume'] > (avg_vol * threshold)
        return df

    def detect_volume_imbalance(self, df: pd.DataFrame):
        """كشف اختلال التوازن في الحجم (Volume Imbalance)"""
        # الفجوة بين إغلاق شمعة وافتتاح الشمعة التالية مع حجم تداول كبير
        imbalances = []
        for i in range(1, len(df)):
            gap = abs(df['open'].iloc[i] - df['close'].iloc[i-1])
            if gap > 0 and df['volume'].iloc[i] > df['volume'].rolling(window=20).mean().iloc[i]:
                imbalances.append({
                    'index': i,
                    'price': (df['open'].iloc[i] + df['close'].iloc[i-1]) / 2,
                    'type': 'BULLISH' if df['close'].iloc[i] > df['open'].iloc[i] else 'BEARISH'
                })
        return imbalances

    def get_volume_profile_bias(self, df: pd.DataFrame):
        """تحديد انحياز ملف الحجم (Volume Profile Bias)"""
        # تحديد السعر الذي تم عنده تداول أكبر حجم (POC - Point of Control)
        # نستخدم تقريب بسيط هنا
        price_bins = pd.cut(df['close'], bins=20)
        volume_profile = df.groupby(price_bins, observed=False)['volume'].sum()
        poc_bin = volume_profile.idxmax()
        poc_price = poc_bin.mid
        
        current_price = df['close'].iloc[-1]
        bias = "BULLISH" if current_price > poc_price else "BEARISH"
        return {"poc": poc_price, "bias": bias}
