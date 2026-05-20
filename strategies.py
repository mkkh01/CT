import pandas as pd
import pandas_ta as ta

class SpotStrategies:
    def __init__(self):
        pass

    def apply_technical_indicators(self, df: pd.DataFrame):
        """تطبيق المؤشرات الفنية الأساسية وتنظيف البيانات الفارغة لمنع الأخطاء الحسابية"""
        if df.empty: return df

        try:
            # 1. RSI (Relative Strength Index)
            df["RSI"] = ta.rsi(df["close"], length=14)

            # 2. MACD (Moving Average Convergence Divergence)
            macd = ta.macd(df["close"], fast=12, slow=26, signal=9)
            if macd is not None and not macd.empty:
                # توحيد أسماء أعمدة الماكد برمجياً لتجنب KeyError القاتل
                macd.columns = ['MACD', 'MACD_HIST', 'MACD_SIGNAL']
                df = pd.concat([df, macd], axis=1)

            # 3. Bollinger Bands
            bbands = ta.bbands(df["close"], length=20, std=2)
            if bbands is not None and not bbands.empty:
                # توحيد أسماء أعمدة البولنجر باند برمجياً لحماية العملات الصفرية
                bbands.columns = ['BBL', 'BBM', 'BBU', 'BBB', 'BBP']
                df = pd.concat([df, bbands], axis=1)

            # 4. ATR (Average True Range)
            df["ATR"] = ta.atr(df["high"], df["low"], df["close"], length=14)

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
