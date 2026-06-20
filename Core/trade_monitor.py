import asyncio
import json
import websockets
import logging
from datetime import datetime
from sqlalchemy import select
from database import AsyncSessionLocal, LiveTrade, TrackedCoin, UserConfig
from config import ADMIN_ID, BINANCE_WS_URL
from Core.redis_manager import redis_client
from Core.state_manager import state_manager
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
        """Periodically save memory data to local cache"""
        try:
            data_to_save = {}
            # Use list() to avoid dictionary size change during iteration
            for symbol, data in list(self.live_prices.items()):
                data_to_save[f"live_prices_{symbol}"] = data
            for symbol, data in list(self.live_klines.items()):
                data_to_save[f"live_klines_{symbol}"] = data
            
            if data_to_save:
                await redis_client.set_batch_data(data_to_save)
        except Exception as e:
            logger.error(f"❌ [MONITOR REDIS] Batch save error: {e}")

    async def check_prices(self):
        """Main entry point for price monitoring"""
        self.is_running = True
        logger.info("🚀 [MONITOR] Starting Price Monitor Loop...")
        
        # Ensure Event Queue workers are running
        if not event_queue.is_running:
            await event_queue.start_workers(num_workers=2)
            
        # Register handler if not already registered
        current_handlers = event_queue.event_handlers.get(EventType.PRICE_UPDATE, [])
        if self._handle_analysis_event not in current_handlers:
            await event_queue.register_handler(EventType.PRICE_UPDATE, self._handle_analysis_event)

        while self.is_running:
            try:
                await self._ws_loop()
            except asyncio.CancelledError:
                logger.info("🛑 [MONITOR] Monitor task cancelled.")
                break
            except Exception as e:
                logger.error(f"❌ [MONITOR] Critical WS Loop Crash: {e}. Restarting in 10s...")
                await asyncio.sleep(10)

    async def _ws_loop(self):
        """Internal WebSocket connection loop"""
        reconnect_delay = 5
        while self.is_running:
            try:
                async with AsyncSessionLocal() as session:
                    coins_res = await session.execute(select(TrackedCoin).where(TrackedCoin.enabled == True))
                    coins = coins_res.scalars().all()
                    symbols = [c.symbol.strip().lower() for c in coins if c.symbol]
                    
                    if not symbols:
                        logger.debug("ℹ️ [MONITOR] No enabled symbols found. Waiting 30s...")
                        await asyncio.sleep(30)
                        continue

                    streams = []
                    symbol_to_tf = {c.symbol.strip().lower(): c.timeframe for c in coins}
                    for s in symbols:
                        streams.append(f"{s}@miniTicker")
                        streams.append(f"{s}@kline_{symbol_to_tf.get(s, '15m')}")

                    uri = f"{BINANCE_WS_URL}/stream?streams={'/'.join(streams)}"
                    
                    logger.info(f"🔌 [MONITOR] Connecting to Binance WS for {len(symbols)} symbols...")
                    async with websockets.connect(uri, ping_interval=20, ping_timeout=20) as ws:
                        reconnect_delay = 5 # Reset on success
                        logger.info("✅ [MONITOR] WebSocket Connected.")
                        
                        while self.is_running:
                            try:
                                msg = await asyncio.wait_for(ws.recv(), timeout=30)
                                await self._handle_message(msg)
                                
                                # Periodic Save to Redis (every 10 seconds approx)
                                if datetime.now().second % 10 == 0:
                                    asyncio.create_task(self._save_data_batch())
                            except asyncio.TimeoutError:
                                # Connection might be dead, try to ping
                                try:
                                    pong = await ws.ping()
                                    await asyncio.wait_for(pong, timeout=5)
                                except:
                                    logger.warning("⚠️ [MONITOR] WS Heartbeat failed. Reconnecting...")
                                    break
                            except Exception as e:
                                if "closed" in str(e).lower():
                                    logger.warning(f"⚠️ [MONITOR] WS Connection closed: {e}")
                                    break
                                logger.error(f"⚠️ [MONITOR] Message handling error: {e}")
                                await asyncio.sleep(1)

            except Exception as e:
                logger.error(f"🔄 [MONITOR] Reconnect attempt failed: {e}")
                if not self.is_running: break
                await asyncio.sleep(reconnect_delay)
                reconnect_delay = min(reconnect_delay * 2, 60)

    async def _handle_message(self, msg):
        """Process incoming WebSocket messages"""
        try:
            payload = json.loads(msg)
            if 'data' not in payload: return
            data = payload['data']
            symbol = data.get('s')
            if not symbol: return

            if 'miniTicker' in payload['stream']:
                price = float(data['c'])
                self.live_prices[symbol] = {
                    'price': price, 
                    'time': datetime.now().strftime('%H:%M:%S')
                }
                # Non-blocking tasks for trade checking and analysis triggering
                asyncio.create_task(self._check_live_trades(symbol, price))
                asyncio.create_task(self._trigger_analysis(symbol, data))
                
            elif 'kline' in payload['stream']:
                k = data['k']
                self.live_klines[symbol] = {
                    'o': float(k['o']), 'h': float(k['h']), 'l': float(k['l']), 
                    'c': float(k['c']), 'v': float(k['v']), 'V': float(k['V']), 'x': k['x']
                }
        except Exception as e:
            logger.error(f"❌ [MONITOR] Handle Msg Error: {e}")

    async def _trigger_analysis(self, symbol, data):
        """Emit analysis event if enough time has passed"""
        symbol_key = symbol.lower()
        now = datetime.now()
        last_time = self._last_analysis_time.get(symbol_key, datetime.min)
        
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
        """Handler for PRICE_UPDATE events from the queue"""
        from Core.ai_engine import AIEngine
        symbol = event.symbol
        async with self._analysis_lock:
            try:
                ai = AIEngine(bot=self.bot, chat_id=self.chat_id)
                live_k = redis_client.get_data(f"live_klines_{symbol}")
                if live_k:
                    await ai.analyze_and_trade(symbol, live_data=live_k)
            except Exception as e:
                logger.error(f"❌ [ANALYSIS ERROR] {symbol}: {e}")

    async def _check_live_trades(self, symbol, price):
        """Check open trades against current price for TP/SL"""
        try:
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
                        if self.bot:
                            icon = "✅" if trade.status == "WON" else "❌"
                            msg = f"{icon} *صفقة مغلقة*\nالرمز: {symbol}\nالربح/الخسارة: {trade.pnl:.2f} USDT"
                            await self.bot.send_message(self.chat_id, msg, parse_mode='Markdown')
        except Exception as e:
            logger.error(f"❌ [CHECK TRADES] Error for {symbol}: {e}")
