import pandas as pd
# استدعاء مؤشرات مكتبة ta المدعومة والمستقرة على Render
from ta.momentum import RSIIndicator
from ta.trend import MACD
from ta.volatility import BollingerBands, AverageTrueRange

class SpotStrategies:
    def __init__(self):
        pass

    def apply_technical_indicators(self, df: pd.DataFrame):
        """تطبيق المؤشرات الفنية الأساسية وتنظيف البيانات الفارغة لمنع الأخطاء الحسابية باستخدام مكتبة ta"""
        if df.empty: return df

        try:
            # 1. حساب RSI
            df["RSI"] = RSIIndicator(close=df["close"], window=14).rsi()

            # 2. حساب MACD - تم تصحيح الخطأ هنا (window_fast)
            macd_indicator = MACD(close=df["close"], window_fast=12, window_slow=26, window_sign=9)
            df['MACD'] = macd_indicator.macd()
            df['MACD_HIST'] = macd_indicator.macd_diff()
            df['MACD_SIGNAL'] = macd_indicator.macd_signal()

            # 3. حساب Bollinger Bands
            bb_indicator = BollingerBands(close=df["close"], window=20, window_dev=2)
            df['BBL'] = bb_indicator.bollinger_lband()
            df['BBM'] = bb_indicator.bollinger_mavg()
            df['BBU'] = bb_indicator.bollinger_hband()

            # 4. حساب ATR
            df["ATR"] = AverageTrueRange(high=df["high"], low=df["low"], close=df["close"], window=14).average_true_range()

            # ملء القيم الفارغة
            df = df.bfill()
            return df
            
        except Exception as e:
            print(f"❌ [STRATEGIES ERROR] فشل حساب المؤشرات الفنية: {e}")
            return df

    def calculate_confidence(self, df: pd.DataFrame, whale_action: str = None, regime: str = "NEUTRAL") -> float:
        """حساب نسبة الثقة الديناميكية لتقرير ما إذا كانت الصفقة 'خاصة' أم 'تدريبية'"""
        if df.empty: return 50.0
        
        last_row = df.iloc[-1]
        confidence = 50.0 
        
        # 1. تحليل المؤشرات الفنية (إضافة حتى 30 درجة)
        if last_row["RSI"] <= 30: confidence += 10
        if last_row["MACD"] > last_row["MACD_SIGNAL"]: confidence += 10
        if last_row["close"] <= last_row["BBL"]: confidence += 10

        # 2. تأثير الحيتان (إضافة حتى 25 درجة)
        if whale_action == "BUY": confidence += 25
        
        # 3. نظام السوق (إضافة حتى 15 درجة)
        if regime == "RISK_ON": confidence += 15
        
        return min(confidence, 100.0)

    def check_buy_signal(self, df: pd.DataFrame) -> bool:
        if df.empty or len(df) < 26: return False
        last_row = df.iloc[-1]
        
        rsi_buy = last_row["RSI"] <= 35
        macd_buy = last_row["MACD"] > last_row["MACD_SIGNAL"]
        bb_buy = last_row["close"] <= (last_row["BBL"] * 1.005)
        
        return rsi_buy or macd_buy or bb_buy

    def get_atr(self, df: pd.DataFrame) -> float:
        if not df.empty and "ATR" in df.columns:
            return float(df["ATR"].iloc[-1])
        return 0.0
