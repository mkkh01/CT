# core/whale_tracker.py
import asyncio
import json
import websockets
from config import WHALE_MIN_VALUE

class WhaleTracker:
    def __init__(self):
        self.active_streams = {}

    async def track_symbol(self, symbol: str):
        """مراقبة الصفقات اللحظية لعملة معينة لاكتشاف الحيتان"""
        uri = f"wss://stream.binance.com:9443/ws/{symbol.lower()}@aggTrade"
        
        print(f"📡 بدء رادار الحيتان لعملة: {symbol}")
        
        async with websockets.connect(uri) as ws:
            self.active_streams[symbol] = ws
            try:
                while True:
                    data = await ws.recv()
                    trade = json.loads(data)
                    
                    price = float(trade['p'])
                    quantity = float(trade['q'])
                    is_buyer_maker = trade['m'] # True = Sell, False = Buy
                    
                    trade_value = price * quantity
                    
                    # اكتشاف الحوت (Dynamic Threshold يمكن إضافته هنا)
                    if trade_value >= WHALE_MIN_VALUE:
                        action = "🔴 بيع" if is_buyer_maker else "🟢 شراء"
                        print(f"🐋 [حوت تم رصده] {symbol} | {action} | القيمة: ${trade_value:,.2f} | السعر: {price}")
                        
                        # هنا سيتم إرسال الإشارة للذكاء الاصطناعي لاحقاً
                        
            except Exception as e:
                print(f"⚠️ انقطع الاتصال لـ {symbol}: {e}")
                del self.active_streams[symbol]

    async def start_tracking(self, symbols_list: list):
        """تشغيل الرادار لعدة عملات في نفس الوقت"""
        tasks = [self.track_symbol(sym) for sym in symbols_list]
        await asyncio.gather(*tasks)
