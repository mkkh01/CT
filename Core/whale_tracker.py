import asyncio
import json
import websockets
from config import BINANCE_WS_URL

class WhaleTracker:
    def __init__(self, bot=None, chat_id=None):
        self.bot = bot
        self.chat_id = chat_id
        self.tracking_symbols = set()  # لتخزين العملات التي يتم تتبعها
        self.min_whale_order_usd = 100000  # قيمة افتراضية للحد الأدنى لطلب الحوت بالدولار

    async def start_tracking(self, symbols: list):
        """بدء تتبع الحيتان لرموز محددة"""
        for symbol in symbols:
            self.tracking_symbols.add(symbol.lower())
        
        print(f"بدء تتبع الحيتان للعملات: {', '.join(self.tracking_symbols)}")
        await self._connect_websocket()

    async def _connect_websocket(self):
        """الاتصال بخدمة Binance WebSocket"""
        while True:
            try:
                # بناء قائمة streams للاشتراك فيها
                streams = [f"{symbol}@trade" for symbol in self.tracking_symbols]
                if not streams:
                    print("لا توجد عملات لتتبعها، سأحاول مرة أخرى بعد 60 ثانية.")
                    await asyncio.sleep(60)
                    continue

                uri = f"{BINANCE_WS_URL}/stream?streams={'/'.join(streams)}"
                print(f"جاري الاتصال بـ WebSocket: {uri}")
                async with websockets.connect(uri) as ws:
                    print("تم الاتصال بنجاح بخدمة Binance WebSocket.")
                    while True:
                        message = await ws.recv()
                        await self._process_message(json.loads(message))
            except websockets.exceptions.ConnectionClosedOK:
                print("تم إغلاق اتصال WebSocket بشكل طبيعي. جاري إعادة الاتصال...")
            except Exception as e:
                print(f"خطأ في اتصال WebSocket: {e}. جاري إعادة الاتصال بعد 5 ثوانٍ...")
                await asyncio.sleep(5)

    async def _process_message(self, message):
        """معالجة الرسائل الواردة من WebSocket"""
        if 'stream' in message and 'data' in message:
            data = message['data']
            if data['e'] == 'trade':
                symbol = data['s']
                price = float(data['p'])
                quantity = float(data['q'])
                is_buyer_maker = data['m'] # True if buyer is maker (sell order), False if seller is maker (buy order)

                # حجم الطلب بالدولار
                order_value_usd = price * quantity

                if order_value_usd >= self.min_whale_order_usd:
                    action = "شراء" if not is_buyer_maker else "بيع"
                    whale_msg = (f"🐳 *تنبيه حوت على {symbol}!*\n\n"
                                 f"العملة: {symbol}\n"
                                 f"النوع: {action}\n"
                                 f"السعر: ${price:,.8f}\n"
                                 f"الكمية: {quantity:,.4f}\n"
                                 f"القيمة: ${order_value_usd:,.2f} USD")
                    
                    print(whale_msg) # طباعة في الكونسول للمراقبة

                    if self.bot and self.chat_id:
                        try:
                            # تم تعديل السطر بالأسفل لمسح الرموز المائلة المسببة للـ SyntaxError
                            await self.bot.send_message(chat_id=self.chat_id, text=whale_msg, parse_mode='Markdown')
                        except Exception as e:
                            print(f"خطأ في إرسال تنبيه الحوت للتليجرام: {e}")

    def add_symbol(self, symbol: str):
        """إضافة عملة جديدة للتتبع"""
        self.tracking_symbols.add(symbol.lower())
        print(f"تمت إضافة {symbol} إلى قائمة تتبع الحيتان.")

    def remove_symbol(self, symbol: str):
        """إزالة عملة من التتبع"""
        self.tracking_symbols.discard(symbol.lower())
        print(f"تمت إزالة {symbol} من قائمة تتبع الحيتان.")

    async def update_tracking_symbols(self, new_symbols: list):
        """تحديث قائمة العملات التي يتم تتبعها"""
        self.tracking_symbols = {s.lower() for s in new_symbols}
        print(f"تم تحديث قائمة تتبع الحيتان إلى: {', '.join(self.tracking_symbols)}")
