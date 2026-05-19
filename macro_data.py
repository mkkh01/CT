# core/macro_data.py
import yfinance as yf
import requests
import asyncio

class MacroAnalyzer:
    def __init__(self):
        self.dxy_ticker = "DX-Y.NYB"
        self.ndx_ticker = "^NDX"

    def get_market_regime(self) -> str:
        """تحديد حالة السوق: Risk-On (شراء) أو Risk-Off (خطر/بيع)"""
        try:
            # جلب بيانات الدولار وناسداك
            dxy = yf.Ticker(self.dxy_ticker).history(period="5d")
            ndx = yf.Ticker(self.ndx_ticker).history(period="5d")
            
            if dxy.empty or ndx.empty:
                return "NEUTRAL"

            dxy_trend = dxy['Close'].iloc[-1] - dxy['Close'].iloc[0]
            ndx_trend = ndx['Close'].iloc[-1] - ndx['Close'].iloc[0]

            # إذا كان الدولار يهبط وناسداك يصعد = بيئة ممتازة للكريبتو
            if dxy_trend < 0 and ndx_trend > 0:
                return "RISK_ON"
            # إذا كان الدولار يطير وناسداك ينهار = خطر
            elif dxy_trend > 0 and ndx_trend < 0:
                return "RISK_OFF"
            
            return "NEUTRAL"
        except Exception as e:
            print(f"⚠️ خطأ في جلب بيانات الماكرو: {e}")
            return "NEUTRAL"

    def get_fear_and_greed(self) -> int:
        """جلب مؤشر الخوف والطمع مجاناً"""
        try:
            response = requests.get("https://api.alternative.me/fng/?limit=1")
            data = response.json()
            return int(data['data'][0]['value'])
        except:
            return 50 # قيمة محايدة في حال الفشل
