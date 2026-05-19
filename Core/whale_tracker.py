# Core/whale_tracker.py
import asyncio
import json
import websockets
import requests
from Core.ai_engine import AIEngine

class WhaleTracker:
    def __init__(self, bot=None, chat_id=None):
        self.active_streams = {}
        self.volume_cache = {}
        self.bot = bot
        self.chat_id = chat_id
        self.ai = AIEngine(bot=bot, chat_id=chat_id) # ربط الذكاء الاصطناعي

    def get_24h_volume(self, symbol: str) -> float:
        if symbol in self.volume_cache:
            return self.volume_cache[symbol]
        try:
            url = f"https://api.binance.com/api/v3/ticker/24hr?symbol={symbol.upper()}"
            res = requests.get(url).json()
            vol = float(res['quoteVolume'])
            self.volume_cache[symbol] = vol
            return vol
        except:
            return 1000000.0 

    async def track_symbol(self, symbol: str):
        uri = f"wss://stream.binance.com:9443/ws/{symbol.lower()}@aggTrade"
        daily_vol = self.get_24h_volume(symbol)
        dynamic_whale_threshold = daily_vol * 0.005 
        
        print(f"📡 رادار {symbol} يعمل | حد الحوت: ${dynamic_whale_threshold:,.2f}")
        
        async with websockets.connect(uri) as ws:
            self.active_streams[symbol] = ws
            try:
                while True:
                    data = await ws.recv()
                    trade = json.loads(data)
                    trade_value = float(trade['p']) * float(trade['q'])
                    is_buyer_maker = trade['m']
                    current_price = float(trade['p'])
                    
                    if trade_value >= dynamic_whale_threshold:
                        action = "🔴 بيع" if is_buyer_maker else "🟢 شراء"
                        msg = f"🐋 *رصد حوت ديناميكي!*\nالعملة: {symbol}\nالنوع: {action}\nالقيمة: ${trade_value:,.2f}\nالسعر: ${current_price}"
                        print(msg)
                        
                        # إرسال إشعار للتليجرام
                        if self.bot and self.chat_id != 0:
                            try:
                                await self.bot.send_message(chat_id=self.chat_id, text=msg, parse_mode='Markdown')
                            except Exception as e:
                                pass
                        
                        # إيقاظ الذكاء الاصطناعي ليحلل الفرصة
                        whale_act = "SELL" if is_buyer_maker else "BUY"
                        atr_estimate = current_price * 0.02 # تقدير مبدئي للتذبذب
                        await self.ai.analyze_and_trade(symbol, current_price, atr_estimate, whale_action=whale_act)
                        
            except Exception as e:
                print(f"⚠️ انقطع الاتصال لـ {symbol}")
                if symbol in self.active_streams:
                    del self.active_streams[symbol]

    async def start_tracking(self, symbols_list: list):
        tasks = [self.track_symbol(sym) for sym in symbols_list]
        if tasks:
            await asyncio.gather(*tasks)
