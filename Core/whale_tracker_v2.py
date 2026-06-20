import asyncio
import json
import websockets
import time
import logging
from config import BINANCE_WS_URL
from Core.redis_manager import redis_client

logger = logging.getLogger(__name__)

class WhaleTrackerV2:
    def __init__(self, bot=None, chat_id=None):
        self.bot = bot
        self.chat_id = chat_id
        self.whale_activity = {} 

    async def process_trade_stream(self, symbol):
        """مراقبة تدفق الصفقات لاكتشاف الحيتان"""
        symbol = symbol.strip()
        uri = f"{BINANCE_WS_URL}/ws/{symbol.lower()}@trade"
        try:
            async with websockets.connect(uri) as ws:
                while True:
                    msg = await ws.recv()
                    data = json.loads(msg)
                    price = float(data['p'])
                    quantity = float(data['q'])
                    value = price * quantity
                    
                    # عتبة الحيتان المؤسسية
                    if value > 100000:
                        side = "SELL" if data['m'] else "BUY"
                        activity_data = {
                            "side": side,
                            "value": value,
                            "time": data['T']
                        }
                        # حفظ النشاط في Redis لضمان الاستمرارية والتكامل
                        redis_client.set_data(f"whale_bias_{symbol}", activity_data, ex=600)
                        
                        if self.bot and self.chat_id:
                            msg_text = (f"🐋 *Whale {side} Detected (V5)*\n"
                                        f"Symbol: {symbol}\n"
                                        f"Value: ${value:,.2f}")
                            try:
                                await self.bot.send_message(self.chat_id, msg_text, parse_mode='Markdown')
                            except: pass
        except Exception as e:
            logger.error(f"❌ [WHALE TRACKER ERROR] {symbol}: {e}")
            await asyncio.sleep(5)

    def get_whale_bias(self, symbol: str) -> str:
        """الحصول على انحياز الحيتان الحالي من Redis"""
        activity = redis_client.get_data(f"whale_bias_{symbol}")
        if activity:
            # التحقق من الصلاحية (10 دقائق)
            if (time.time() * 1000 - activity['time']) < 600000:
                return activity['side']
        return "NEUTRAL"
