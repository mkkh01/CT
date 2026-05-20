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
            # 1. حساب RSI (Relative Strength Index)
            df["RSI"] = RSIIndicator(close=df["close"], window=14).rsi()

            # 2. حساب MACD (Moving Average Convergence Divergence)
            macd_indicator = MACD(close=df["close"], window_fast=12, window_slow=26, window_sign=9)
            df['MACD'] = macd_indicator.macd()
            df['MACD_HIST'] = macd_indicator.macd_diff()
            df['MACD_SIGNAL'] = macd_indicator.macd_signal()

            # 3. حساب Bollinger Bands وتوحيد أسماء الأعمدة لحماية العملات الصفرية
            bb_indicator = BollingerBands(close=df["close"], window=20, window_dev=2)
            df['BBL'] = bb_indicator.bollinger_lband()  # الحد السفلي
            df['BBM'] = bb_indicator.bollinger_mavg()   # الحد الأوسط
            df['BBU'] = bb_indicator.bollinger_hband()  # الحد العلوي
            df['BBB'] = bb_indicator.bollinger_wband()  # العرض (Width)
            df['BBP'] = bb_indicator.bollinger_pband()  # النسبة المنوية (Percentage)

            # 4. حساب ATR (Average True Range) بأمان تام لمدير المخاطر
            df["ATR"] = AverageTrueRange(high=df["high"], low=df["low"], close=df["close"], window=14).average_true_range()

            # ملء وتطهير القيم الفارغة الأولى الناتجة عن فترات حساب المؤشرات الفنية
            df = df.fillna(method='bfill')
            return df
            
        except Exception as e:
            print(f"❌ [STRATEGIES ERROR] فشل حساب المؤشرات الفنية: {e}")
            return df

    def check_buy_signal(self, df: pd.DataFrame) -> bool:
        """التحقق من إشارة شراء مرنة ومتوافقة مع رادار الحيتان والمبالغ الصغيرة"""
        if df.empty or len(df) < 26: 
            return False

        last_row = df.iloc[-1]
        prev_row = df.iloc[-2]

        # تأمين التحقق من وجود الأعمدة الموحدة قبل المقارنة الرقمية
        required_cols = ["RSI", "MACD", "MACD_SIGNAL", "close", "BBL"]
        if not all(col in df.columns for col in required_cols):
            print("⚠️ [STRATEGIES] بعض الأعمدة الفنية مفقودة من الـ DataFrame، تخطي فحص الشراء.")
            return False

        # 1. شرط RSI مرن: المنطقة تحت 35 تعني تشبع بيعي فرصة صعود، أو ارتداد الـ 30 للأعلى
        rsi_buy = last_row["RSI"] <= 35 or (prev_row["RSI"] < 30 and last_row["RSI"] >= 30)
        
        # 2. شرط MACD: تقاطع خط الماكد مع خط الإشارة للأعلى (Bullish Crossover)
        macd_buy = last_row["MACD"] > last_row["MACD_SIGNAL"] and prev_row["MACD"] <= prev_row["MACD_SIGNAL"]
        
        # 3. شرط Bollinger Bands: السعر ملامس أو قريب جداً من الحد السفلي (منطقة دعم مرنة مع تفاوت 0.5%)
        bb_buy = last_row["close"] <= (last_row["BBL"] * 1.005)

        print(f"📊 [STRATEGIES CHECK] فحص الشراء الفني -> RSI: {rsi_buy} | MACD: {macd_buy} | BB: {bb_buy}")
        return rsi_buy or macd_buy or bb_buy

    def check_sell_signal(self, df: pd.DataFrame) -> bool:
        """التحقق من إشارة بيع مرنة فنية تتماشى مع تقلبات السوق اللحظية"""
        if df.empty or len(df) < 26:
            return False

        last_row = df.iloc[-1]
        prev_row = df.iloc[-2]

        required_cols = ["RSI", "MACD", "MACD_SIGNAL", "close", "BBU"]
        if not all(col in df.columns for col in required_cols):
            return False

        # 1. شرط RSI للبيع: فوق 65 منطقة خطرة، أو كسر الـ 70 للأسفل
        rsi_sell = last_row["RSI"] >= 65 or (prev_row["RSI"] > 70 and last_row["RSI"] <= 70)
        
        # 2. شرط MACD للبيع: تقاطع خط الماكد للأسفل (Bearish Crossover)
        macd_sell = last_row["MACD"] < last_row["MACD_SIGNAL"] and prev_row["MACD"] >= prev_row["MACD_SIGNAL"]
        
        # 3. شرط Bollinger Bands للبيع: السعر ملامس أو قريب من الحد العلوي (مقاومة مع تفاوت 0.5%)
        bb_sell = last_row["close"] >= (last_row["BBU"] * 0.995)

        print(f"📊 [STRATEGIES CHECK] فحص البيع الفني -> RSI: {rsi_sell} | MACD: {macd_sell} | BB: {bb_sell}")
        return rsi_sell or macd_sell or bb_sell

    def get_atr(self, df: pd.DataFrame) -> float:
        """جلب قيمة ATR بأمان تام لمنع الأخطاء الصفرية"""
        if not df.empty and "ATR" in df.columns:
            return float(df["ATR"].iloc[-1])
        return 0.0
