import asyncio
import json
import websockets
from datetime import datetime
from sqlalchemy import select
from database import AsyncSessionLocal, PaperTrade, TrackedCoin, UserConfig
from config import ADMIN_ID

class TradeMonitor:
    def __init__(self, bot=None):
        self.bot = bot
        self.chat_id = ADMIN_ID
        self.is_running = False

    async def check_prices(self):
        from Core.ai_engine import AIEngine
        ai = AIEngine(bot=self.bot, chat_id=self.chat_id)
        self.is_running = True
        print("📡 تم تشغيل الرادار والمراقب اللحظي V3.1 بنجاح.")
        
        while self.is_running:
            try:
                async with AsyncSessionLocal() as session:
                    # 1. فحص نشاط النظام
                    cfg_res = await session.execute(select(UserConfig).limit(1))
                    cfg = cfg_res.scalars().first()
                    if not cfg or not cfg.is_active:
                        await asyncio.sleep(20)
                        continue

                    # 2. جولة صيد الصفقات (Scan)
                    coins_res = await session.execute(select(TrackedCoin))
                    tracked_list = coins_res.scalars().all()
                    
                    for coin in tracked_list:
                        try:
                            await ai.analyze_and_trade(coin.symbol)
                        except Exception as e:
                            print(f"⚠️ خطأ في تحليل {coin.symbol}: {e}")
                        await asyncio.sleep(1)

                    # 3. جلب الصفقات المفتوحة للمراقبة
                    trades_res = await session.execute(select(PaperTrade).where(PaperTrade.status == "OPEN"))
                    symbols = list(set([t.symbol for t in trades_res.scalars().all()]))

                if symbols:
                    streams = [f"{s.lower()}@miniTicker" for s in symbols]
                    uri = f"wss://stream.binance.com:9443/stream?streams={'/'.join(streams)}"
                    async with websockets.connect(uri) as ws:
                        # مراقبة لمدة 3 دقائق قبل جولة الفحص القادمة
                        for _ in range(180):
                            try:
                                msg = await asyncio.wait_for(ws.recv(), timeout=5)
                                await self._process_price_update(json.loads(msg))
                            except asyncio.TimeoutError:
                                continue
                            except Exception:
                                break
                            await asyncio.sleep(1)
                else:
                    await asyncio.sleep(15)

            except Exception as e:
                print(f"⚠️ خطأ في المراقبة الرئيسية: {e}")
                await asyncio.sleep(10)

    async def _process_price_update(self, message):
        if 'data' not in message: return
        data = message['data']
        symbol, current_price = data['s'], float(data['c'])

        async with AsyncSessionLocal() as session:
            res = await session.execute(select(PaperTrade).where((PaperTrade.symbol == symbol) & (PaperTrade.status == "OPEN")))
            for trade in res.scalars().all():
                closed, status = False, ""
                if trade.side == "BUY":
                    if current_price >= trade.take_profit: closed, status = True, "WON"
                    elif current_price <= trade.stop_loss: closed, status = True, "LOST"
                elif trade.side == "SELL":
                    if current_price <= trade.take_profit: closed, status = True, "WON"
                    elif current_price >= trade.stop_loss: closed, status = True, "LOST"

                if closed:
                    trade.status, trade.exit_price, trade.closed_at = status, current_price, datetime.utcnow()
                    await session.commit()
                    icon = "✅" if status == "WON" else "❌"
                    msg = f"{icon} *إغلاق صفقة*\\n\\nالعملة: {symbol}\\nالنتيجة: {status}\\nالدخول: {trade.entry_price}\\nالخروج: {current_price}"
                    if self.bot: await self.bot.send_message(self.chat_id, msg, parse_mode='Markdown')
