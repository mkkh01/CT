import asyncio
from datetime import datetime
import json
# from textblob import TextBlob # تم تعطيلها لعدم الحاجة لها
import requests

class NewsIntelligence:
    def __init__(self, bot=None, chat_id=None):
        self.bot = bot
        self.chat_id = chat_id

    async def fetch_realtime_news_headlines(self, symbol: str):
        """جلب عناوين الأخبار بشكل مجاني (محاكاة أو عبر RSS مفتوح)"""
        # في النسخة المجانية، يمكننا استخدام محركات بحث مفتوحة أو RSS
        # هنا سنعتمد على تحليل "المشاعر العامة" للنصوص المتاحة
        return f"Market sentiment analysis for {symbol} based on technical structure and volume."

    async def analyze_sentiment_free(self, text: str):
        """تحليل المشاعر (تم تعطيله للاعتماد على التحليل الفني فقط)"""
        polarity = 0 # محايد افتراضياً
        
        if polarity > 0.1:
            impact = "Bullish"
            score = 80
            decision = "TRADE"
        elif polarity < -0.1:
            impact = "Bearish"
            score = 30
            decision = "AVOID"
        else:
            impact = "Neutral"
            score = 60
            decision = "WAIT"
            
        return {
            "economic_news": "Global market flow analysis",
            "currency_news": "Technical sentiment analysis",
            "impact": impact,
            "safety_score": score,
            "decision": decision,
            "reason": f"Sentiment analysis score: {polarity:.2f} (Free Engine)"
        }

    async def get_safety_check(self, symbol: str) -> bool:
        """التحقق من الأمان باستخدام المحرك المجاني"""
        context = await self.fetch_realtime_news_headlines(symbol)
        analysis = await self.analyze_sentiment_free(context)
        
        # السماح بالتداول إذا كان الشعور العام ليس سلبياً جداً
        if analysis.get("safety_score", 0) >= 50:
            return True
        return False

# لتوافق الكود القديم مع الجديد
class NewsAnalyzer(NewsIntelligence):
    pass
