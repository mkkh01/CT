import aiohttp
import asyncio

class MarketContext:
    def __init__(self):
        self.base_url = "https://api.binance.com/api/v3"

    async def get_symbol_price(self, symbol):
        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(f"{self.base_url}/ticker/price?symbol={symbol}") as resp:
                    data = await resp.json()
                    return float(data['price'])
            except:
                return None

    async def get_market_regime(self):
        """تحليل حالة السوق العامة (BTC, ETH, Dominance)"""
        btc_price = await self.get_symbol_price("BTCUSDT")
        eth_price = await self.get_symbol_price("ETHUSDT")
        
        # ملاحظة: في النسخة الحقيقية يفضل جلب Dominance من TradingView أو API متخصص
        # هنا سنفترض بناءً على حركة BTC
        if not btc_price: return "NEUTRAL"
        
        # محاكاة بسيطة للارتباط
        if btc_price > 0: # مجرد فحص للوجود
            return "BULLISH_MARKET" if btc_price > 50000 else "BEARISH_MARKET"
        
        return "NEUTRAL"

    def check_correlation_safety(self, symbol, market_regime):
        """التأكد من أن الصفقة تتماشى مع اتجاه السوق العام"""
        if market_regime == "BEARISH_MARKET" and "USDT" in symbol:
            # في سوق هابط، نفضل عدم الشراء إلا بشروط قوية جداً
            return False
        return True
