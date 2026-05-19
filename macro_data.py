# macro_data.py
import yfinance as yf
import requests
import time

class MacroAnalyzer:
    def __init__(self):
        self.dxy_ticker = "DX-Y.NYB"
        self.ndx_ticker = "^NDX"
        # إعداد الذاكرة المؤقتة (Cache)
        self._cache = {"regime": None, "fng": None, "regime_time": 0, "fng_time": 0}
        self.cache_duration = 3600  # حفظ البيانات لمدة ساعة (3600 ثانية)

    def get_market_regime(self) -> str:
        current_time = time.time()
        # إذا كانت البيانات موجودة ولم تمر ساعة، استخدمها فوراً
        if self._cache["regime"] and (current_time - self._cache["regime_time"] < self.cache_duration):
            return self._cache["regime"]
            
        try:
            dxy = yf.Ticker(self.dxy_ticker).history(period="5d")
            ndx = yf.Ticker(self.ndx_ticker).history(period="5d")
            if dxy.empty or ndx.empty: return "NEUTRAL"
            
            dxy_trend = dxy['Close'].iloc[-1] - dxy['Close'].iloc[0]
            ndx_trend = ndx['Close'].iloc[-1] - ndx['Close'].iloc[0]

            if dxy_trend < 0 and ndx_trend > 0: 
                regime = "RISK_ON"
            elif dxy_trend > 0 and ndx_trend < 0: 
                regime = "RISK_OFF"
            else: 
                regime = "NEUTRAL"
            
            # حفظ النتيجة في الذاكرة المؤقتة
            self._cache["regime"] = regime
            self._cache["regime_time"] = current_time
            return regime
            
        except Exception as e:
            print(f"⚠️ تنبيه ماكرو (تم استخدام الذاكرة المؤقتة): {e}")
            return self._cache["regime"] or "NEUTRAL"

    def get_fear_and_greed(self) -> int:
        current_time = time.time()
        if self._cache["fng"] and (current_time - self._cache["fng_time"] < self.cache_duration):
            return self._cache["fng"]
            
        try:
            res = requests.get("https://api.alternative.me/fng/?limit=1").json()
            fng = int(res['data'][0]['value'])
            
            self._cache["fng"] = fng
            self._cache["fng_time"] = current_time
            return fng
        except:
            return self._cache["fng"] or 50
