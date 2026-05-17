import pandas as pd
import ta
from logger import setup_logger

logger = setup_logger("MultiTimeframeAnalyzer")

class MultiTimeframeAnalyzer:
    @staticmethod
    def _prepare_dataframe(candles) -> pd.DataFrame:
        """
        دالة داخلية لتحويل مصفوفة الشموع الخام إلى DataFrame 
        وحساب المؤشرات الأساسية بشكل آمن.
        """
        if not candles or len(candles) < 30:
            return pd.DataFrame()
            
        df = pd.DataFrame(candles, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        
        # 1. حساب مؤشر القوة النسبية (RSI)
        df['rsi'] = ta.momentum.rsi(df['close'], window=14)
        
        # 2. حساب مؤشر الماكد (MACD)
        macd = ta.trend.MACD(df['close'])
        df['macd'] = macd.macd()
        df['macd_signal'] = macd.macd_signal()
        
        # 3. حساب المتوسط المتحرك الأسي (EMA 20) لإيجاد مناطق الدعم والمقاومة الحركية
        df['ema_20'] = ta.trend.ema_indicator(df['close'], window=20)
        
        # 4. حساب مؤشر متوسط المدى الحقيقي (ATR) لقياس المسافات السعرية للـ SL و TP
        df['atr'] = ta.volatility.average_true_range(df['high'], df['low'], df['close'], window=14)
        
        return df

    @classmethod
    def analyze(cls, candles_5m, candles_15m, candles_1h) -> dict:
        """
        دمج وتحليل المؤشرات لجميع الأطر الزمنية المطلوبة في نفس اللحظة
        لتوفير رؤية ثلاثية الأبعاد لحركة السعر.
        """
        try:
            df_5m = cls._prepare_dataframe(candles_5m)
            df_15m = cls._prepare_dataframe(candles_15m)
            df_1h = cls._prepare_dataframe(candles_1h)
            
            # التحقق من سلامة واكتمال معالجة البيانات لكافة الأطر
            if df_5m.empty or df_15m.empty or df_1h.empty:
                logger.warning("بيانات الأطر الزمنية غير كاملة، تخطي عملية التحليل.")
                return None

            # استخراج القيم اللحظية الأخيرة بدقة
            analysis_result = {
                "5m": {
                    "close": float(df_5m['close'].iloc[-1]),
                    "rsi": float(df_5m['rsi'].iloc[-1]) if not pd.isna(df_5m['rsi'].iloc[-1]) else 50.0,
                    "macd": float(df_5m['macd'].iloc[-1]),
                    "macd_sig": float(df_5m['macd_signal'].iloc[-1]),
                    "atr": float(df_5m['atr'].iloc[-1])
                },
                "15m": {
                    "close": float(df_15m['close'].iloc[-1]),
                    "rsi": float(df_15m['rsi'].iloc[-1]) if not pd.isna(df_15m['rsi'].iloc[-1]) else 50.0,
                    "ema_20": float(df_15m['ema_20'].iloc[-1])
                },
                "1h": {
                    "close": float(df_1h['close'].iloc[-1]),
                    "rsi": float(df_1h['rsi'].iloc[-1]) if not pd.isna(df_1h['rsi'].iloc[-1]) else 50.0,
                    "ema_20": float(df_1h['ema_20'].iloc[-1])
                }
            }
            
            return analysis_result
            
        except Exception as e:
            logger.error(f"خطأ غير متوقع أثناء معالجة البيانات الفنية للأطر: {str(e)}")
            return None
