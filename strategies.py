import pandas as pd
import pandas_ta as ta

class SpotStrategies:
    def __init__(self):
        pass

    def apply_technical_indicators(self, df: pd.DataFrame):
        """تطبيق المؤشرات الفنية الأساسية على بيانات الشموع"""
        if df.empty: return df

        # RSI (Relative Strength Index)
        df["RSI"] = ta.rsi(df["close"], length=14)

        # MACD (Moving Average Convergence Divergence)
        macd = ta.macd(df["close"], fast=12, slow=26, signal=9)
        df = pd.concat([df, macd], axis=1)

        # Bollinger Bands
        bbands = ta.bbands(df["close"], length=20, std=2)
        df = pd.concat([df, bbands], axis=1)

        # ATR (Average True Range)
        df["ATR"] = ta.atr(df["high"], df["low"], df["close"], length=14)

        return df

    def check_buy_signal(self, df: pd.DataFrame) -> bool:
        """التحقق من إشارة شراء بناءً على المؤشرات الفنية"""
        if df.empty or len(df) < 20: # نحتاج لبيانات كافية للمؤشرات
            return False

        last_row = df.iloc[-1]
        prev_row = df.iloc[-2]

        # مثال بسيط لإشارة شراء:
        # RSI أقل من 30 (تشبع بيعي) وبدأ في الارتفاع
        # MACD يعبر خط الإشارة للأعلى
        # السعر قريب من الحد السفلي لـ Bollinger Bands

        rsi_buy = last_row["RSI"] < 30 and last_row["RSI"] > prev_row["RSI"]
        macd_buy = last_row["MACD_12_26_9"] > last_row["MACDs_12_26_9"] and prev_row["MACD_12_26_9"] < prev_row["MACDs_12_26_9"]
        bb_buy = last_row["close"] < last_row["BBL_20_2.0"]

        return rsi_buy or macd_buy or bb_buy

    def check_sell_signal(self, df: pd.DataFrame) -> bool:
        """التحقق من إشارة بيع بناءً على المؤشرات الفنية"""
        if df.empty or len(df) < 20:
            return False

        last_row = df.iloc[-1]
        prev_row = df.iloc[-2]

        # مثال بسيط لإشارة بيع:
        # RSI أعلى من 70 (تشبع شرائي) وبدأ في الانخفاض
        # MACD يعبر خط الإشارة للأسفل
        # السعر قريب من الحد العلوي لـ Bollinger Bands

        rsi_sell = last_row["RSI"] > 70 and last_row["RSI"] < prev_row["RSI"]
        macd_sell = last_row["MACD_12_26_9"] < last_row["MACDs_12_26_9"] and prev_row["MACD_12_26_9"] > prev_row["MACDs_12_26_9"]
        bb_sell = last_row["close"] > last_row["BBU_20_2.0"]

        return rsi_sell or macd_sell or bb_sell

    def get_atr(self, df: pd.DataFrame) -> float:
        """جلب قيمة ATR من البيانات المحسوبة"""
        if not df.empty and "ATR" in df.columns:
            return df["ATR"].iloc[-1]
        return 0.0
