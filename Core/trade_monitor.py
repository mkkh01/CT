import asyncio
import json
import websockets
import os
from datetime import datetime
from sqlalchemy import select
from database import AsyncSessionLocal, LiveTrade, TrackedCoin, UserConfig
from config import ADMIN_ID

from Core.redis_manager import redis_client

class TradeMonitor:
    def __init__(self, bot=None):
        self.bot = bot
        self.chat_id = ADMIN_ID
        self.is_running = False
        # استعادة البيانات من Redis عند البدء لضمان الاستمرارية
        self.live_prices = redis_client.get_data("live_prices") or {}
        self.live_klines = redis_client.get_data("live_klines") or {}

    def _save_data(self):
        # حفظ البيانات في Redis بدلاً من الملفات المحلية
        redis_client.set_data("live_prices", self.live_prices)
        redis_client.set_data("live_klines", self.live_klines)

    async def check_prices(self):
        from Core.ai_engine import AIEngine
        ai = AIEngine(bot=self.bot, chat_id=self.chat_id)
        self.is_running = True
        print("📡 [MONITOR] انطلاق الرادار المؤسسي V4.0")
        
        while self.is_running:
            try:
                async with AsyncSessionLocal() as session:
                    coins_res = await session.execute(select(TrackedCoin).where(TrackedCoin.enabled == True))
                    symbols = [c.symbol.strip() for c in coins_res.scalars().all() if c.symbol and c.symbol.strip()]
                    
                    if not symbols:
                        await asyncio.sleep(10)
                        continue

                    # تنظيف الرموز لضمان عدم وجود مسافات أو رموز فارغة تسبب HTTP 400
                    streams = [f"{s.lower()}@miniTicker" for s in symbols] + [f"{s.lower()}@kline_15m" for s in symbols]
                    streams = [st for st in streams if st]
                    uri = f"wss://stream.binance.com:9443/stream?streams={'/'.join(streams)}"
                    
                    async with websockets.connect(uri) as ws:
                        # ضبط الوقت الأولي ليبدأ الفحص بعد 30 ثانية من استقرار الاتصال
                        from datetime import timedelta
                        last_analysis_time = datetime.now() - timedelta(seconds=90)
                        
                        while self.is_running:
                            # التحقق من وجود عملات جديدة تمت إضافتها لإعادة الاتصال
                            async with AsyncSessionLocal() as check_session:
                                current_symbols = [c.symbol for c in (await check_session.execute(select(TrackedCoin).where(TrackedCoin.enabled == True))).scalars().all()]
                                if set(current_symbols) != set(symbols):
                                    print("🔄 [MONITOR] تم اكتشاف تغيير في العملات، إعادة تشغيل البث...")
                                    break # سيخرج من الحلقة الداخلية ويعيد الاتصال بالقائمة الجديدة

                            try:
                                msg = await asyncio.wait_for(ws.recv(), timeout=5)
                                payload = json.loads(msg)
                                data = payload['data']
                                symbol = data['s']
                            except asyncio.TimeoutError:
                                continue
                            
                            if 'miniTicker' in payload['stream']:
                                price = float(data['c'])
                                self.live_prices[symbol] = {'price': price, 'time': datetime.now().strftime('%H:%M:%S')}
                                await self._check_live_trades(symbol, price)
                            elif 'kline' in payload['stream']:
                                k = data['k']
                                self.live_klines[symbol] = {'o': float(k['o']), 'h': float(k['h']), 'l': float(k['l']), 'c': float(k['c']), 'v': float(k['v']), 'x': k['x']}
                            
                            self._save_data()

                            if (datetime.now() - last_analysis_time).total_seconds() >= 120: # تقليل الفاصل الزمني إلى دقيقتين ليكون أكثر استجابة
                                print(f"📡 [MONITOR] جاري فحص {len(symbols)} عملة بحثاً عن فرص تداول...")
                                for s in symbols:
                                    # نقوم بالتحليل إذا توفرت بيانات من الـ WebSocket أو الـ Redis
                                    if s in self.live_klines or s in self.live_prices:
                                        print(f"🔍 [SCANNER] جاري تحليل {s}...")
                                        await ai.analyze_and_trade(s)
                                        await asyncio.sleep(1.5) # تأخير معقول بين العملات
                                last_analysis_time = datetime.now()

            except Exception as e:
                import traceback
                print(f"⚠️ [MONITOR] Fatal Error: {e}")
                traceback.print_exc()
                await asyncio.sleep(5)

    async def _check_live_trades(self, symbol, price):
        """مراقبة الصفقات الحقيقية (Phase 4)"""
        async with AsyncSessionLocal() as session:
            res = await session.execute(select(LiveTrade).where((LiveTrade.symbol == symbol) & (LiveTrade.status == "OPEN")))
            for trade in res.scalars().all():
                closed = False
                if trade.type == "BUY":
                    if price >= trade.take_profit:
                        trade.status, closed = "WON", True
                        trade.exit_reason = "Take Profit Hit"
                    elif price <= trade.stop_loss:
                        trade.status, closed = "LOST", True
                        trade.exit_reason = "Stop Loss Hit"
                
                if closed:
                    trade.exit_price = price
                    trade.closed_at = datetime.utcnow()
                    trade.duration = (trade.closed_at - trade.timestamp).seconds
                    pnl_pct = ((price - trade.entry_price) / trade.entry_price) * 100
                    trade.pnl = (trade.amount * pnl_pct) / 100
                    
                    # Capital Protection Engine (Phase 4)
                    if trade.status == "LOST":
                        cfg_res = await session.execute(select(UserConfig).where(UserConfig.telegram_id == self.chat_id))
                        cfg = cfg_res.scalars().first()
                        cfg.consecutive_losses += 1
                        if cfg.consecutive_losses >= 5:
                            cfg.emergency_stop = True
                            if self.bot: await self.bot.send_message(self.chat_id, "🚨 *EMERGENCY STOP*: 5 consecutive losses detected!")
                    else:
                        cfg_res = await session.execute(select(UserConfig).where(UserConfig.telegram_id == self.chat_id))
                        cfg = cfg_res.scalars().first()
                        cfg.consecutive_losses = 0

                    await session.commit()
                    if self.bot:
                        icon = "✅" if trade.status == "WON" else "❌"
                        await self.bot.send_message(self.chat_id, f"{icon} *صفقة مغلقة*\n{symbol}: {trade.pnl:.2f} USDT")
