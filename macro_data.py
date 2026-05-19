import yfinance as yf
import requests
import json
from datetime import datetime, timedelta

class MacroAnalyzer:
    def __init__(self):
        self.cache = {}
        self.cache_duration = timedelta(hours=1) # تحديث البيانات كل ساعة

    def _is_cache_valid(self, key):
        if key in self.cache:
            timestamp, _ = self.cache[key]
            return datetime.now() - timestamp < self.cache_duration
        return False

    def get_dxy(self) -> float:
        """جلب مؤشر الدولار الأمريكي (DXY) من Yahoo Finance"""
        key = "DXY"
        if self._is_cache_valid(key):
            return self.cache[key][1]
        
        try:
            # DXY يتم تتبعه عادةً كـ DX-Y.NYB أو ^DXY في بعض المصادر
            # yfinance لا يدعم DXY مباشرة بشكل موثوق، لذا سنستخدم طريقة بديلة أو نعتمد على مؤشر بديل
            # للتبسيط، سنستخدم مؤشر SPY كبديل مؤقت أو نعتمد على مصدر خارجي إذا كان متاحاً
            # هنا، سنفترض أننا نحصل عليه من مصدر موثوق أو نستخدم قيمة ثابتة للتدريب
            # في بيئة الإنتاج، يجب استبدال هذا بمصدر بيانات DXY حقيقي
            # For now, let's simulate with a fixed value or a placeholder
            # dxy_data = yf.Ticker("DX-Y.NYB").history(period="1d") # قد لا يعمل دائماً
            # if not dxy_data.empty: 
            #     dxy_value = dxy_data["Close"].iloc[-1]
            # else:
            #     dxy_value = 100.0 # قيمة افتراضية
            
            # Placeholder for DXY, in a real system this would be fetched from a reliable API
            dxy_value = 105.0 # قيمة افتراضية
            self.cache[key] = (datetime.now(), dxy_value)
            return dxy_value
        except Exception as e:
            print(f"خطأ في جلب DXY: {e}")
            return 100.0 # قيمة افتراضية عند الخطأ

    def get_ndx(self) -> float:
        """جلب مؤشر ناسداك 100 (NDX) من Yahoo Finance"""
        key = "NDX"
        if self._is_cache_valid(key):
            return self.cache[key][1]

        try:
            ndx_data = yf.Ticker("^NDX").history(period="1d")
            if not ndx_data.empty: 
                ndx_value = ndx_data["Close"].iloc[-1]
                self.cache[key] = (datetime.now(), ndx_value)
                return ndx_value
            else:
                return 15000.0 # قيمة افتراضية
        except Exception as e:
            print(f"خطأ في جلب NDX: {e}")
            return 15000.0 # قيمة افتراضية عند الخطأ

    def get_fear_and_greed(self) -> int:
        """جلب مؤشر الخوف والجشع (Fear & Greed Index)"""
        key = "FNG"
        if self._is_cache_valid(key):
            return self.cache[key][1]

        try:
            # مصدر موثوق لمؤشر الخوف والجشع
            url = "https://api.alternative.me/fng/?limit=1"
            response = requests.get(url)
            data = response.json()
            fng_value = int(data["data"][0]["value"])
            self.cache[key] = (datetime.now(), fng_value)
            return fng_value
        except Exception as e:
            print(f"خطأ في جلب مؤشر الخوف والجشع: {e}")
            return 50 # قيمة افتراضية (محايد) عند الخطأ

    def get_market_regime(self) -> str:
        """تحديد وضع السوق بناءً على مؤشرات الماكرو"""
        dxy = self.get_dxy()
        ndx = self.get_ndx()
        fng = self.get_fear_and_greed()

        # منطق بسيط لتحديد وضع السوق
        if dxy > 103 and ndx < 15500 and fng < 30: # دولار قوي، أسهم ضعيفة، خوف
            return "RISK_OFF"
        elif dxy < 100 and ndx > 16000 and fng > 70: # دولار ضعيف، أسهم قوية، جشع
            return "RISK_ON"
        else:
            return "NEUTRAL"

