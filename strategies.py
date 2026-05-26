import pandas as pd
# استدعاء مؤشرات مكتبة ta المدعومة والمستقرة على Render
from ta.momentum import RSIIndicator
from ta.trend import MACD
from ta.volatility import BollingerBands, AverageTrueRange

class SpotStrategies:
    def __init__(self):
        pass

    def apply_technical_indicators(self, df: pd.DataFrame):
        """تطبيق المؤشرات الفنية الأساسية مع تنظيف البيانات بشكل احترافي"""
        if df is None or df.empty: 
            return pd.DataFrame()

        try:
            # التأكد من أن البيانات أرقام (Float)
            for col in ['open', 'high', 'low', 'close', 'volume']:
                df[col] = pd.to_numeric(df[col], errors='coerce')

            # 1. حساب RSI
            df["RSI"] = RSIIndicator(close=df["close"], window=14).rsi()

            # 2. حساب MACD
            macd_indicator = MACD(close=df["close"], window_fast=12, window_slow=26, window_sign=9)
            df['MACD'] = macd_indicator.macd()
            df['MACD_SIGNAL'] = macd_indicator.macd_signal()
            df['MACD_HIST'] = macd_indicator.macd_diff()

            # 3. حساب Bollinger Bands
            bb_indicator = BollingerBands(close=df["close"], window=20, window_dev=2)
            df['BBL'] = bb_indicator.bollinger_lband()
            df['BBM'] = bb_indicator.bollinger_mavg()
            df['BBU'] = bb_indicator.bollinger_hband()

            # 4. حساب ATR لقياس التذبذب وتحديد الأهداف
            df["ATR"] = AverageTrueRange(high=df["high"], low=df["low"], close=df["close"], window=14).average_true_range()

            # تنظيف القيم الناتجة عن الحسابات الأولى (NaN)
            df = df.ffill().dropna()
            return df
            
        except Exception as e:
            print(f"❌ [STRATEGIES ERROR] خطأ في الحسابات الفنية: {e}")
            return df

    def calculate_confidence(self, df: pd.DataFrame, whale_action: str = None, regime: str = "NEUTRAL") -> float:
        """حساب نسبة الثقة (Confidence Score) لتحديد نوع الصفقة (نخبة أم تدريب)"""
        if df.empty: return 0.0
        
        last_row = df.iloc[-1]
        confidence = 50.0 # نقطة البداية المتوازنة
        
        # 1. تحليل RSI (تحسين الأوزان لصفقات النخبة)
        if last_row["RSI"] <= 30: 
            confidence += 15
        elif last_row["RSI"] <= 40: 
            confidence += 7
        elif last_row["RSI"] >= 70: # تشبع شرائي - تقليل الثقة للشراء
            confidence -= 20

        # 2. تقاطع MACD الإيجابي (الزخم)
        if last_row["MACD"] > last_row["MACD_SIGNAL"]:
            confidence += 10
            if last_row["MACD_HIST"] > 0: 
                confidence += 5 # تأكيد استمرارية الصعود

        # 3. ملامسة حدود البولنجر السفلى (مناطق الارتداد القوية)
        if last_row["close"] <= last_row["BBL"]:
            confidence += 15
        elif last_row["close"] <= (last_row["BBL"] * 1.01):
            confidence += 5

        # 4. تأثير رادار الحيتان (الوزن الأكبر 25%)
        if whale_action == "BUY": 
            confidence += 25
        elif whale_action == "SELL":
            confidence -= 30
        
        # 5. حالة السوق العام (Risk-On / Risk-Off)
        if regime == "RISK_ON": 
            confidence += 15
        elif regime == "RISK_OFF":
            confidence -= 25 # حماية النخبة من الانهيارات السوقية
        
        # التأكد من أن القيمة بين 0 و 100
        return float(max(0.0, min(confidence, 100.0)))

    def check_buy_signal(self, df: pd.DataFrame) -> bool:
        """شرط الدخول المبدئي لفتح صفقة تدريب (حتى لو لم تكن نخبة)"""
        if df.empty or len(df) < 20: return False
        
        last_row = df.iloc[-1]
        
        # شروط مبسطة لفتح صفقات "التدريب" لجمع البيانات
        rsi_buy = last_row["RSI"] <= 45
        macd_buy = last_row["MACD"] > last_row["MACD_SIGNAL"]
        bb_near = last_row["close"] <= (last_row["BBL"] * 1.005)
        
        # يكفي تحقق شرطين لفتح صفقة تدريب مخفية
        signals = [rsi_buy, macd_buy, bb_near]
        return sum(signals) >= 2

    def get_atr(self, df: pd.DataFrame) -> float:
        """جلب قيمة ATR الحالية لحساب الوقف والأهداف"""
        if not df.empty and "ATR" in df.columns:
            return float(df["ATR"].iloc[-1])
        return 0.0
