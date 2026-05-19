# Core/whale_tracker.py
import asyncio
import json
import websockets
import requests

class WhaleTracker:
    def __init__(self):
        self.active_streams = {}
        self.volume_cache = {}

    def get_24h_volume(self, symbol: str) -> float:
        """جلب حجم التداول اليومي للعملة لتحديد حجم الحوت ديناميكياً"""
        if symbol in self.volume_cache:
            return self.volume_cache[symbol]
            
        try:
            url = f"https://api.binance.com/api/v3/ticker/24hr?symbol={symbol.upper()}"
            res = requests.get(url).json()
            vol = float(res['quoteVolume'])
            self.volume_cache[symbol] = vol
            return vol
        except:
            return 1000000.0 # قيمة افتراضية

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
                    
                    if trade_value >= dynamic_whale_threshold:
                        action = "🔴 بيع" if is_buyer_maker else "🟢 شراء"
                        print(f"🐋 [حوت ديناميكي] {symbol} | {action} | القيمة: ${trade_value:,.2f}")
            except Exception as e:
                print(f"⚠️ انقطع الاتصال لـ {symbol}")
                del self.active_streams[symbol]

    async def start_tracking(self, symbols_list: list):
        """تشغيل الرادار لعدة عملات في نفس الوقت"""
        tasks = [self.track_symbol(sym) for sym in symbols_list]
        await asyncio.gather(*tasks)
