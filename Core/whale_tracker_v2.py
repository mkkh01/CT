import asyncio
import json
import websockets

class WhaleTrackerV2:
    def __init__(self, bot=None, chat_id=None):
        self.bot = bot
        self.chat_id = chat_id
        self.whale_activity = {} # {symbol: last_action_time}

    async def process_trade_stream(self, symbol):
        uri = f"wss://stream.binance.com:9443/ws/{symbol.lower()}@trade"
        async with websockets.connect(uri) as ws:
            while True:
                msg = await ws.recv()
                data = json.loads(msg)
                price = float(data['p'])
                quantity = float(data['q'])
                value = price * quantity
                
                # عتبة الحيتان: 100 ألف دولار
                if value > 100000:
                    side = "SELL" if data['m'] else "BUY"
                    self.whale_activity[symbol] = {
                        "side": side,
                        "value": value,
                        "time": data['T']
                    }
                    if self.bot and self.chat_id:
                        await self.bot.send_message(
                            self.chat_id, 
                            f"🐋 *Whale {side} Detected*\nSymbol: {symbol}\nValue: ${value:,.2f}"
                        )

    def get_whale_bias(self, symbol):
        """الحصول على انحياز الحيتان الحالي للعملة"""
        activity = self.whale_activity.get(symbol)
        if activity:
            # صالح لمدة 10 دقائق فقط
            import time
            if (time.time() * 1000 - activity['time']) < 600000:
                return activity['side']
        return "NEUTRAL"
