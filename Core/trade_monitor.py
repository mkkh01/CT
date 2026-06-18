import asyncio
import json
import websockets
import os
from datetime import datetime
from sqlalchemy import select
from database import AsyncSessionLocal, LiveTrade, TrackedCoin, UserConfig
from config import ADMIN_ID

from Core.redis_manager import redis_client
from Core.state_manager import state_manager, SystemState

class TradeMonitor:
    def __init__(self, bot=None):
        self.bot = bot
        self.chat_id = ADMIN_ID
        self.is_running = False
        self.live_prices = {}
        self.live_klines = {}

    async def _save_data(self):
        async with state_manager.cache_lock:
            for symbol, data in self.live_prices.items():
                await redis_client.set_data(f"live_prices_{symbol}", data)
            for symbol, data in self.live_klines.items():
                await redis_client.set_data(f"live_klines_{symbol}", data)

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
                    
                    try:
                        async with websockets.connect(uri, ping_interval=20, ping_timeout=10) as ws:
                            # ضبط الوقت الأولي ليبدأ الفحص بعد 30 ثانية من استقرار الاتصال
                            from datetime import timedelta
                            last_analysis_time = datetime.now() - timedelta(seconds=90)
                            
                            while self.is_running:
                                try:
                                    # التحقق من وجود عملات جديدة تمت إضافتها لإعادة الاتصال
                                    async with AsyncSessionLocal() as check_session:
                                        current_symbols = [c.symbol for c in (await check_session.execute(select(TrackedCoin).where(TrackedCoin.enabled == True))).scalars().all()]
                                        if set(current_symbols) != set(symbols):
                                            print("🔄 [MONITOR] تم اكتشاف تغيير في العملات، إعادة تشغيل البث...")
                                            break # سيخرج من الحلقة الداخلية ويعيد الاتصال بالقائمة الجديدة

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
                                except asyncio.CancelledError:
                                    print("⚠️ [MONITOR] TradeMonitor task cancelled during websocket operation.")
                                    raise # Re-raise to propagate cancellation
                                except Exception as e:
                                    print(f"⚠️ [MONITOR] Error processing message: {e}")
                                    continue
                                
                                async with state_manager.cache_lock:
                                    if 'miniTicker' in payload['stream']:
                                        price = float(data['c'])
                                        await redis_client.set_data(f"live_prices_{symbol}", {'price': price, 'time': datetime.now().strftime('%H:%M:%S')})
                                        await self._check_live_trades(symbol, price)
                                    elif 'kline' in payload['stream']:
                                        k = data['k']
                                        await redis_client.set_data(f"live_klines_{symbol}", {'o': float(k['o']), 'h': float(k['h']), 'l': float(k['l']), 'c': float(k['c']), 'v': float(k['v']), 'x': k['x']})
                                
                                await self._save_data()

                                # لا يسمح بالتحليل إلا إذا كان النظام READY (بعد انتهاء الـ Warm-up)
                                if state_manager.is_ready() and (datetime.now() - last_analysis_time).total_seconds() >= 120:
                                    print(f"📡 [MONITOR] بدأت دورة التحليل المؤسسي لـ {len(symbols)} عملة...")
                                    # تحديد حد أقصى لعدد الرموز التي تتم معالجتها في كل دورة (مثلاً 4 رموز فقط)
                                    processed_symbols_count = 0
                                    for s in symbols:
                                        if processed_symbols_count >= 4:
                                            print("⚠️ [SCANNER] تم الوصول للحد الأقصى من الرموز المعالجة في هذه الدورة (4 رموز).")
                                            break

                                        live_k = redis_client.get_data(f"live_klines_{s}")
                                        
                                        if live_k:
                                            print(f"🔍 [SCANNER] جاري تحليل {s} بناءً على بيانات الـ WebSocket المحدثة...")
                                            await ai.analyze_and_trade(s, live_data=live_k)
                                            await asyncio.sleep(0.5)
                                            processed_symbols_count += 1
                                        else:
                                            print(f"⚠️ [SCANNER] تخطي {s} لعدم توفر بيانات كافية في الكاش.")
                                    
                                    print("✅ [SYSTEM] اكتملت دورة التحليل بنجاح.")
                                    last_analysis_time = datetime.now()
                                    reconnect_delay = 5
                    except websockets.exceptions.ConnectionClosedOK:
                        print("🔌 [MONITOR] WebSocket connection closed gracefully.")
                    except websockets.exceptions.ConnectionClosedError as e:
                        print(f"❌ [MONITOR] WebSocket connection closed with error: {e}")
                    except Exception as e:
                        import traceback
                        print(f"❌ [CRITICAL ERROR] Unhandled exception in TradeMonitor WebSocket block: {e}\n{traceback.format_exc()}")
                    finally:
                        print("🔄 [MONITOR] إعادة محاولة الاتصال بـ WebSocket...")

                await asyncio.sleep(reconnect_delay) # Wait before restarting the loop
            except asyncio.CancelledError:
                print("🛑 [MONITOR] TradeMonitor task was cancelled. Shutting down gracefully.")
                self.is_running = False
                break # Exit the loop on cancellation
            except Exception as e:
                import traceback
                print(f"⚠️ [MONITOR] Connection Error in main loop: {e}. Reconnecting in {reconnect_delay}s...\n{traceback.format_exc()}")
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
