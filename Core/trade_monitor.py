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
                    coins = coins_res.scalars().all()
                    symbols = [c.symbol.strip() for c in coins if c.symbol and c.symbol.strip()]
                    
                    if not symbols:
                        await asyncio.sleep(10)
                        continue

                    clean_symbols = [s.strip().lower() for s in symbols if s and s.strip()]
                    if not clean_symbols:
                        await asyncio.sleep(10)
                        continue
                        
                    streams = []
                    # خريطة لربط الرمز بـ timeframe الخاص به
                    symbol_to_tf = {c.symbol.strip().lower(): c.timeframe for c in coins}
                    
                    for s in clean_symbols:
                        if s.isalnum():
                            streams.append(f"{s}@miniTicker")
                            tf = symbol_to_tf.get(s, "15m")
                            streams.append(f"{s}@kline_{tf}")
                    
                    if not streams:
                        await asyncio.sleep(10)
                        continue

                    uri = f"wss://stream.binance.com:9443/stream?streams={'/'.join(streams)}"
                    
                    try:
                        async with websockets.connect(uri, ping_interval=20, ping_timeout=10) as ws:
                            from datetime import timedelta
                            last_analysis_time = datetime.now() - timedelta(seconds=90)
                            
                            while self.is_running:
                                try:
                                    async with AsyncSessionLocal() as check_session:
                                        current_symbols = [c.symbol for c in (await check_session.execute(select(TrackedCoin).where(TrackedCoin.enabled == True))).scalars().all()]
                                        if set(current_symbols) != set(symbols):
                                            print("🔄 [MONITOR] تم اكتشاف تغيير في العملات، إعادة تشغيل البث...")
                                            break

                                    msg = await asyncio.wait_for(ws.recv(), timeout=20)
                                    payload = json.loads(msg)
                                    if 'data' not in payload or 'stream' not in payload:
                                        continue
                                    data = payload['data']
                                    symbol = data.get('s')
                                    if not symbol:
                                        continue
                                except asyncio.TimeoutError:
                                    try:
                                        pong_waiter = await ws.ping()
                                        await asyncio.wait_for(pong_waiter, timeout=5)
                                    except:
                                        break
                                    continue
                                except asyncio.CancelledError:
                                    raise
                                except Exception as e:
                                    print(f"⚠️ [MONITOR] Error processing message: {e}")
                                    continue
                                
                                async with state_manager.cache_lock:
                                    if 'miniTicker' in payload['stream']:
                                        price = float(data['c'])
                                        self.live_prices[symbol] = {'price': price, 'time': datetime.now().strftime('%H:%M:%S')}
                                        await self._check_live_trades(symbol, price)
                                    elif 'kline' in payload['stream']:
                                        k = data['k']
                                        self.live_klines[symbol] = {'o': float(k['o']), 'h': float(k['h']), 'l': float(k['l']), 'c': float(k['c']), 'v': float(k['v']), 'x': k['x']}
                                    
                                    await self._save_data()

                                if state_manager.is_ready() and (datetime.now() - last_analysis_time).total_seconds() >= 120:
                                    print(f"📡 [MONITOR] بدأت دورة التحليل المؤسسي لـ {len(symbols)} عملة...")
                                    processed_symbols_count = 0
                                    for s in symbols:
                                        if processed_symbols_count >= 4:
                                            break

                                        live_k = redis_client.get_data(f"live_klines_{s}")
                                        if live_k:
                                            await ai.analyze_and_trade(s, live_data=live_k)
                                            await asyncio.sleep(0.5)
                                            processed_symbols_count += 1
                                    
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

                await asyncio.sleep(reconnect_delay)
            except asyncio.CancelledError:
                self.is_running = False
                break
            except Exception as e:
                import traceback
                print(f"⚠️ [MONITOR] Connection Error in main loop: {e}. Reconnecting in {reconnect_delay}s...\n{traceback.format_exc()}")
                await asyncio.sleep(reconnect_delay)
                reconnect_delay = min(reconnect_delay * 2, 300)

    async def _check_live_trades(self, symbol, price):
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
                    
                    if trade.status == "LOST":
                        cfg_res = await session.execute(select(UserConfig).where(UserConfig.telegram_id == self.chat_id))
                        cfg = cfg_res.scalars().first()
                        if cfg:
                            cfg.consecutive_losses += 1
                            if cfg.consecutive_losses >= 5:
                                cfg.emergency_stop = True
                                if self.bot: await self.bot.send_message(self.chat_id, "🚨 *EMERGENCY STOP*: 5 consecutive losses detected!")
                    else:
                        cfg_res = await session.execute(select(UserConfig).where(UserConfig.telegram_id == self.chat_id))
                        cfg = cfg_res.scalars().first()
                        if cfg:
                            cfg.consecutive_losses = 0

                    await session.commit()
                    if self.bot:
                        icon = "✅" if trade.status == "WON" else "❌"
                        await self.bot.send_message(self.chat_id, f"{icon} *صفقة مغلقة*\n{symbol}: {trade.pnl:.2f} USDT")
