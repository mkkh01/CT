import pandas as pd
import numpy as np
import ta
from logger import setup_logger

logger = setup_logger("MarketRegime")

class MarketRegimeDetector:
    @staticmethod
    def detect(df: pd.DataFrame) -> dict:
        """
        تحليل هيكلية الحركة السعرية ومستويات السيولة لتحديد حالة السوق بدقة:
        - TRENDING_BULLISH (اتجاه صاعد صريح)
        - TRENDING_BEARISH (اتجاه هابط صريح)
        - RANGING (سوق عرضي متزن)
        - CHOPPY (سوق عشوائي متذبذب حاد - خطير)
        - PANIC (انهيار وهلع بيعي سريع)
        - HIGH_VOLATILITY (تقلبات حادة غير مستقرة)
        """
        try:
            if df is None or df.empty or len(df) < 50:
                return {"regime": "UNKNOWN", "volatility": 0.0, "bb_width": 0.0, "rsi": 50.0}

            close = df['close']
            high = df['high']
            low = df['low']
            
            # 1. حساب مؤشر متوسط المدى الحقيقي (ATR) منسوباً للنسبة المئوية للسعر
            atr_ind = ta.volatility.average_true_range(high, low, close, window=14)
            latest_close = close.iloc[-1]
            latest_atr_pct = (atr_ind.iloc[-1] / latest_close) * 100 if latest_close > 0 else 0.0
            
            # 2. حساب اتساع نطاق حزم بولينجر (Bollinger Bands Width) لكشف الاختناق والانفجار السعري
            bb_width = ta.volatility.bollinger_wband(close, window=20, window_dev=2)
            latest_bbw = bb_width.iloc[-1] if not pd.isna(bb_width.iloc[-1]) else 0.0
            
            # 3. حساب المتوسطات المتحركة الأسية (EMA) لكشف البنية الاتجاهية
            ema_50 = ta.trend.ema_indicator(close, window=50)
            ema_200 = ta.trend.ema_indicator(close, window=200)
            
            latest_ema50 = ema_50.iloc[-1]
            latest_ema200 = ema_200.iloc[-1]
            
            # 4. حساب مؤشر القوة النسبية (RSI) لكشف ذروة البيع والشراء
            rsi_ind = ta.momentum.rsi(close, window=14)
            latest_rsi = rsi_ind.iloc[-1] if not pd.isna(rsi_ind.iloc[-1]) else 50.0
            
            # ------------------------------------------------------------------
            # محرك اتخاذ القرار الهيكلي لحالة السوق (Decision Engine Logic)
            # ------------------------------------------------------------------
            
            # أ. حالة الهلع والانهيار الشديد
            if latest_rsi < 22 and latest_atr_pct > 6.0:
                regime = "PANIC"
                
            # ب. حالة التقلب المفرط (خروج السعر عن السيطرة الفنية)
            elif latest_atr_pct > 8.0 or latest_bbw > 0.35:
                regime = "HIGH_VOLATILITY"
                
            # ج. حالة النطاق الضيق العشوائي (الفرم الحاد للأموال / Whipsaw)
            elif latest_bbw < 0.03:
                regime = "CHOPPY"
                
            # د. الاتجاه الصاعد الصريح (السيولة تدعم الارتفاع المستمر)
            elif latest_close > latest_ema50 > latest_ema200:
                regime = "TRENDING_BULLISH"
                
            # هـ. الاتجاه الهابط الصريح (السيولة تدفع للهبوط المستمر)
            elif latest_close < latest_ema50 < latest_ema200:
                regime = "TRENDING_BEARISH"
                
            # و. السوق العرضي النظيف (الموجات المنتظمة داخل قنوات محددة)
            else:
                regime = "RANGING"
                
            return {
                "regime": regime,
                "volatility": float(latest_atr_pct),
                "bb_width": float(latest_bbw),
                "rsi": float(latest_rsi)
            }
            
        except Exception as e:
            logger.error(f"خطأ غير متوقع أثناء فحص بيئة السوق: {str(e)}")
            return {"regime": "ERROR", "volatility": 0.0, "bb_width": 0.0, "rsi": 50.0}
