import ccxt.pro as ccxtpro
import asyncio
from logger import setup_logger

logger = setup_logger("ExchangeManager")

class ExchangeManager:
    def __init__(self):
        # تفعيل الاتصالات مع المنصات الثلاث المطلوبة مع تفعيل محددات معدل الطلبات (Rate Limiting)
        # لمنع حظر الـ IP الخاص بالسيرفر تلقائياً
        self.exchanges = {
            'binance': ccxtpro.binance({'enableRateLimit': True}),
            'bybit': ccxtpro.bybit({'enableRateLimit': True}),
            'okx': ccxtpro.okx({'enableRateLimit': True})
        }

    async def fetch_candles(self, symbol: str, timeframe: str = '1h', limit: int = 100):
        """
        جلب بيانات الشموع اليابانية بشكل غير متزامن مع آلية التحول التلقائي (Fallback)
        في حال فشل المنصة الأساسية في الاستجابة.
        """
        # محاولة جلب البيانات بالترتيب: Binance ثم Bybit ثم OKX
        for name, exchange in self.exchanges.items():
            try:
                # جلب بيانات الشموع (Open, High, Low, Close, Volume)
                ohlcv = await exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
                
                if not ohlcv or len(ohlcv) < limit:
                    logger.warning(f"بيانات ناقصة أو غير كافية من منصة {name} للزوج {symbol}")
                    continue
                
                # ------------------------------------------------------------------
                # نظام التحقق الصارم من صحة البيانات (Data Validation Engine)
                # ------------------------------------------------------------------
                validated_candles = []
                for candle in ohlcv:
                    timestamp, open_p, high_p, low_p, close_p, volume = candle
                    
                    # 1. كشف واستبعاد الشموع ذات الأحجام الصفرية أو الوهمية (Fake/Abnormal Volume)
                    if volume <= 0:
                        continue
                        
                    # 2. كشف واستبعاد الشموع المشوهة فريالياً (Abnormal Spikes / Invalid Structure)
                    if high_p < low_p or open_p <= 0 or close_p <= 0:
                        continue
                        
                    # 3. التحقق من منطقية الأرقام (تجنب القفزات السعرية المعدومة الناتجة عن أخطاء الـ API)
                    if high_p < open_p or high_p < close_p or low_p > open_p or low_p > close_p:
                        continue
                        
                    validated_candles.append(candle)
                
                # إذا كانت البيانات بعد الفلترة كافية ومستقرة، يتم اعتمادها فوراً ويغلق الفحص
                if len(validated_candles) >= (limit * 0.9):  # قبول هامش خطأ بسيط جداً في الشموع القديمة
                    return validated_candles
                    
                logger.warning(f"تم رفض بيانات {name} للزوج {symbol} بسبب عدم اجتياز فلاتر السلامة الفنية.")
                
            except Exception as e:
                logger.error(f"فشل الاتصال أو جلب البيانات من {name} للزوج {symbol}: {str(e)}")
                # الاستمرار في الحلقة التكرارية لتجربة المنصة البديلة التالية تلقائياً
                continue
                
        # في حال فشل جميع المنصات في جلب بيانات موثوقة
        logger.critical(f"فشل ذريع: جميع المنصات المتاحة فشلت في تزويد النظام ببيانات موثوقة للزوج {symbol}")
        return None

    async def close_connections(self):
        """
        إغلاق كافة اتصالات الـ WebSockets والـ Sessions بشكل نظيف عند إيقاف النظام
        """
        for name, exchange in self.exchanges.items():
            try:
                await exchange.close()
                logger.info(f"تم إغلاق الاتصال بمنصة {name} بنجاح.")
            except Exception as e:
                logger.error(f"خطأ أثناء إغلاق اتصال {name}: {str(e)}")
