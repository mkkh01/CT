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
        from Core.api_guard import api_guard
        ai = AIEngine(bot=self.bot, chat_id=self.chat_id)
        self.is_running = True
        print("🚀 [SYSTEM] انطلاق محرك التداول المؤسسي CT V5.0")
        print("📡 [MONITOR] بدء مراقبة الأسعار عبر WebSocket...")
        
        reconnect_delay = 5
        while self.is_running:
            try:
                await api_guard.check_wait(1)
                async with AsyncSessionLocal() as session:
                    coins_res = await session.execute(select(TrackedCoin).where(TrackedCoin.enabled == True))
                    symbols = [c.symbol.strip() for c in coins_res.scalars().all() if c.symbol and c.symbol.strip()]
                    
                    if not symbols:
                        await asyncio.sleep(10)
                        continue

                    # تنظيف صارم للرموز لضمان عدم وجود رموز غير صالحة تسبب HTTP 400
                    clean_symbols = [s.strip().lower() for s in symbols if s and s.strip()]
                    if not clean_symbols:
                        await asyncio.sleep(10)
                        continue
                        
                    streams = []
                    for s in clean_symbols:
                        # التأكد من أن الرمز لا يحتوي على مسافات داخلية أو رموز غريبة
                        if s.isalnum():
                            streams.append(f"{s}@miniTicker")
                            streams.append(f"{s}@kline_15m")
                    
                    if not streams:
                        await asyncio.sleep(10)
                        continue

                    uri = f"wss://stream.binance.com:9443/stream?streams={'/'.join(streams)}"
                    
                    async with websockets.connect(uri, ping_interval=20, ping_timeout=10) as ws:
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
                                msg = await asyncio.wait_for(ws.recv(), timeout=20)
                                payload = json.loads(msg)
                                if 'data' not in payload or 'stream' not in payload:
                                    continue
                                data = payload['data']
                                symbol = data.get('s')
                                if not symbol:
                                    continue
                            except asyncio.TimeoutError:
                                # إرسال Ping للحفاظ على الاتصال
                                try:
                                    pong_waiter = await ws.ping()
                                    await asyncio.wait_for(pong_waiter, timeout=5)
                                except:
                                    break # إعادة الاتصال إذا فشل الـ Ping
                                continue
                            except Exception as e:
                                print(f"⚠️ [MONITOR] Error processing message: {e}")
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
                                print(f"📡 [MONITOR] بدأت دورة التحليل المؤسسي لـ {len(symbols)} عملة...")
                                for s in symbols:
                                    # استخدام البيانات المخزنة مؤقتاً (Cache) لتقليل طلبات REST
                                    if s in self.live_klines:
                                        print(f"🔍 [SCANNER] جاري تحليل {s} بناءً على بيانات الـ WebSocket المحدثة...")
                                        await ai.analyze_and_trade(s, live_data=self.live_klines[s])
                                        await asyncio.sleep(0.5) # تقليل التأخير لاعتمادنا على الكاش
                                    else:
                                        print(f"⚠️ [SCANNER] تخطي {s} لعدم توفر بيانات كافية في الكاش.")
                                
                                print("✅ [SYSTEM] اكتملت دورة التحليل بنجاح. بانتظار الدورة القادمة.")
                                last_analysis_time = datetime.now()
                                reconnect_delay = 5 # Reset delay on success

            except Exception as e:
                import traceback
                print(f"⚠️ [MONITOR] Connection Error: {e}. Reconnecting in {reconnect_delay}s...")
                await asyncio.sleep(reconnect_delay)
                reconnect_delay = min(reconnect_delay * 2, 300) # Exponential backoff for WS reconnect

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
