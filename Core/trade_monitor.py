import asyncio
import json
import websockets
import logging
from datetime import datetime, timedelta
from sqlalchemy import select
from database import AsyncSessionLocal, LiveTrade, TrackedCoin, UserConfig
from config import ADMIN_ID, BINANCE_WS_URL
from Core.redis_manager import redis_client
from Core.state_manager import state_manager, SystemState
from Core.event_queue import event_queue, EventType

logger = logging.getLogger(__name__)

class TradeMonitor:
    def __init__(self, bot=None):
        self.bot = bot
        self.chat_id = ADMIN_ID
        self.is_running = False
        self.live_prices = {}
        self.live_klines = {}
        self._analysis_lock = asyncio.Lock()
        self._last_analysis_time = {}

    async def _save_data_batch(self):
        """حفظ البيانات دفعة واحدة لتقليل عمليات الكتابة"""
        try:
            data_to_save = {}
            for symbol, data in self.live_prices.items():
                data_to_save[f"live_prices_{symbol}"] = data
            for symbol, data in self.live_klines.items():
                data_to_save[f"live_klines_{symbol}"] = data
            
            if data_to_save:
                await redis_client.set_batch_data(data_to_save)
        except Exception as e:
            logger.error(f"❌ [REDIS] Error saving batch data: {e}")

    async def check_prices(self):
        from Core.ai_engine import AIEngine
        from Core.api_guard import api_guard
        
        ai = AIEngine(bot=self.bot, chat_id=self.chat_id)
        self.is_running = True
        logger.info("🚀 [MONITOR] بدء مراقبة الأسعار عبر WebSocket...")
        
        # بدء معالجي الأحداث (Workers)
        if not event_queue.is_running:
            await event_queue.start_workers(num_workers=2)
            # تسجيل معالج التحليل
            await event_queue.register_handler(EventType.PRICE_UPDATE, self._handle_analysis_event)

        reconnect_delay = 5
        max_reconnect_delay = 300

        while self.is_running:
            try:
                async with AsyncSessionLocal() as session:
                    coins_res = await session.execute(select(TrackedCoin).where(TrackedCoin.enabled == True))
                    coins = coins_res.scalars().all()
                    symbols = [c.symbol.strip().lower() for c in coins if c.symbol]
                    
                    if not symbols:
                        logger.info("ℹ️ [MONITOR] لا توجد عملات مفعلة للمراقبة. الانتظار...")
                        await asyncio.sleep(30)
                        continue

                    streams = []
                    symbol_to_tf = {c.symbol.strip().lower(): c.timeframe for c in coins}
                    for s in symbols:
                        streams.append(f"{s}@miniTicker")
                        streams.append(f"{s}@kline_{symbol_to_tf.get(s, '15m')}")

                    uri = f"{BINANCE_WS_URL}/stream?streams={'/'.join(streams)}"
                    
                    logger.info(f"🔌 [MONITOR] محاولة الاتصال بـ WebSocket لـ {len(symbols)} عملة...")
                    
                    async with websockets.connect(uri, ping_interval=20, ping_timeout=10) as ws:
                        reconnect_delay = 5 # Reset delay on successful connection
                        logger.info("✅ [MONITOR] تم الاتصال بنجاح.")
                        
                        while self.is_running:
                            try:
                                msg = await asyncio.wait_for(ws.recv(), timeout=25)
                                payload = json.loads(msg)
                                
                                if 'data' not in payload: continue
                                data = payload['data']
                                symbol = data.get('s')
                                if not symbol: continue

                                # تحديث البيانات في الذاكرة
                                if 'miniTicker' in payload['stream']:
                                    price = float(data['c'])
                                    self.live_prices[symbol] = {
                                        'price': price, 
                                        'time': datetime.now().strftime('%H:%M:%S')
                                    }
                                    # التحقق من الصفقات المفتوحة
                                    await self._check_live_trades(symbol, price)
                                    
                                    # إرسال حدث للتحليل إذا مر وقت كافٍ
                                    await self._trigger_analysis(symbol, data)
                                    
                                elif 'kline' in payload['stream']:
                                    k = data['k']
                                    self.live_klines[symbol] = {
                                        'o': float(k['o']), 'h': float(k['h']), 
                                        'l': float(k['l']), 'c': float(k['c']), 
                                        'v': float(k['v']), 'x': k['x']
                                    }

                                # حفظ دوري للبيانات
                                if datetime.now().second % 10 == 0:
                                    await self._save_data_batch()

                            except asyncio.TimeoutError:
                                # محاولة إرسال Ping للحفاظ على الاتصال
                                try:
                                    pong = await ws.ping()
                                    await asyncio.wait_for(pong, timeout=5)
                                except:
                                    logger.warning("⚠️ [MONITOR] WebSocket ping timeout, reconnecting...")
                                    break
                            except Exception as e:
                                logger.error(f"⚠️ [MONITOR] Error in message loop: {e}")
                                break

                if self.is_running:
                    logger.info(f"🔄 [MONITOR] إعادة الاتصال خلال {reconnect_delay} ثانية...")
                    await asyncio.sleep(reconnect_delay)
                    reconnect_delay = min(reconnect_delay * 1.5, max_reconnect_delay)

            except asyncio.CancelledError:
                self.is_running = False
                break
            except Exception as e:
                logger.error(f"❌ [MONITOR] Critical error in main loop: {e}", exc_info=True)
                await asyncio.sleep(reconnect_delay)
                reconnect_delay = min(reconnect_delay * 2, max_reconnect_delay)

    async def _trigger_analysis(self, symbol, data):
        """إرسال طلب تحليل إلى الطابور مع منع التكرار القريب"""
        # Binance sends symbols in uppercase, we use lowercase in our mapping
        symbol_key = symbol.lower()
        now = datetime.now()
        last_time = self._last_analysis_time.get(symbol_key, datetime.min)
        
        # لا نحلل نفس العملة أكثر من مرة كل 60 ثانية
        if (now - last_time).total_seconds() < 60:
            return

        if state_manager.is_ready():
            self._last_analysis_time[symbol_key] = now
            await event_queue.emit_event(
                event_type=EventType.PRICE_UPDATE,
                symbol=symbol_key,
                data={'price': float(data['c']), 'raw': data},
                source="TRADE_MONITOR",
                worker_name="ws_listener",
                priority=3
            )

    async def _handle_analysis_event(self, event):
        """معالج الحدث الذي يتم استدعاؤه بواسطة Queue Worker"""
        from Core.ai_engine import AIEngine
        symbol = event.symbol
        
        # قفل لضمان عدم تحليل نفس الرمز مرتين بالتوازي
        async with self._analysis_lock:
            try:
                ai = AIEngine(bot=self.bot, chat_id=self.chat_id)
                live_k = redis_client.get_data(f"live_klines_{symbol}")
                if live_k:
                    logger.info(f"🧠 [ANALYSIS] بدء تحليل {symbol}...")
                    start_time = datetime.now()
                    await ai.analyze_and_trade(symbol, live_data=live_k)
                    duration = (datetime.now() - start_time).total_seconds()
                    logger.info(f"✅ [ANALYSIS] اكتمل تحليل {symbol} في {duration:.2f} ثانية.")
                else:
                    logger.warning(f"⚠️ [ANALYSIS] لم يتم العثور على بيانات حية لـ {symbol} في الكاش.")
            except Exception as e:
                logger.error(f"❌ [ANALYSIS ERROR] {symbol}: {e}", exc_info=True)

    async def _check_live_trades(self, symbol, price):
        """التحقق من أهداف الربح ووقف الخسارة"""
        try:
            # Ensure symbol is uppercase for DB matching
            symbol_db = symbol.upper()
            async with AsyncSessionLocal() as session:
                res = await session.execute(
                    select(LiveTrade).where((LiveTrade.symbol == symbol_db) & (LiveTrade.status == "OPEN"))
                )
                trades = res.scalars().all()
                if not trades: return

                for trade in trades:
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
                        
                        # تحديث إحصائيات المستخدم
                        cfg_res = await session.execute(select(UserConfig).where(UserConfig.telegram_id == self.chat_id))
                        cfg = cfg_res.scalars().first()
                        if cfg:
                            if trade.status == "LOST":
                                cfg.consecutive_losses += 1
                                if cfg.consecutive_losses >= 5:
                                    cfg.emergency_stop = True
                                    if self.bot: 
                                        await self.bot.send_message(self.chat_id, "🚨 *EMERGENCY STOP*: 5 consecutive losses detected!")
                            else:
                                cfg.consecutive_losses = 0

                        await session.commit()
                        logger.info(f"💰 [TRADE CLOSED] {symbol} | Status: {trade.status} | PnL: {trade.pnl:.2f}")
                        
                        if self.bot:
                            icon = "✅" if trade.status == "WON" else "❌"
                            msg = f"{icon} *صفقة مغلقة*\nالرمز: {symbol}\nالربح/الخسارة: {trade.pnl:.2f} USDT\nالسبب: {trade.exit_reason}"
                            await self.bot.send_message(self.chat_id, msg, parse_mode='Markdown')
        except Exception as e:
            logger.error(f"❌ [MONITOR] Error checking live trades for {symbol}: {e}")
