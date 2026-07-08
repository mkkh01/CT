import asyncio
import json
import time
import websockets
import os
from datetime import datetime
from sqlalchemy import select
from database import AsyncSessionLocal, LiveTrade, TrackedCoin, UserConfig
from config import ADMIN_ID, DEBUG_MODE
from Core.redis_client import redis_client
from Core.diagnostics import get_diagnostics, is_debug

logger_ws = __import__("logging").getLogger("CT_Monitor")


class TradeMonitor:
    def __init__(self, bot=None):
        self.bot = bot
        self.chat_id = ADMIN_ID
        self.is_running = False
        self.live_prices = redis_client.get_data("live_prices") or {}
        self.live_klines = redis_client.get_data("live_klines") or {}

        # WebSocket stats for diagnostics
        self._ws_connected = False
        self._ws_reconnect_attempts = 0
        self._ws_last_msg_time: float = 0
        self._ws_msg_count: int = 0
        self._ws_last_msg_desc: str = ""
        self._ws_latency_ms: float = 0
        self._last_diag_time: float = 0

    def _save_data(self):
        redis_client.set_data("live_prices", self.live_prices, ttl=3600)
        redis_client.set_data("live_klines", self.live_klines, ttl=3600)

    def _emit_ws_diagnostics(self):
        """Emit WebSocket health diagnostics at intervals."""
        now = time.time()
        if now - self._last_diag_time < 300:  # every 5 minutes
            return
        self._last_diag_time = now

        elapsed = max(now - self._ws_last_msg_time, 0.001) if self._ws_last_msg_time else 0
        msgs_per_min = (self._ws_msg_count / max(elapsed / 60, 0.001)) if elapsed else 0

        diag = get_diagnostics()
        diag.websocket_stats(
            connected=self._ws_connected,
            symbols_count=len(self.live_prices),
            messages_per_min=msgs_per_min,
            latency_ms=self._ws_latency_ms,
            last_message=self._ws_last_msg_desc,
            reconnect_attempts=self._ws_reconnect_attempts,
        )

    async def check_prices(self):
        from Core.ai_engine import AIEngine
        ai = AIEngine(bot=self.bot)
        self.is_running = True
        logger_ws.info("📡 [MONITOR] Institutional radar V4.0 — WebSocket Mode")

        while self.is_running:
            try:
                async with AsyncSessionLocal() as session:
                    coins_res = await session.execute(
                        select(TrackedCoin).where(TrackedCoin.enabled == True)
                    )
                    coins = coins_res.scalars().all()
                    symbols = [c.symbol for c in coins]

                    if not symbols:
                        logger_ws.info("ℹ️  [MONITOR] No active coins — waiting...")
                        self._emit_ws_diagnostics()
                        await asyncio.sleep(15)
                        continue

                    streams = [f"{s.lower()}@miniTicker" for s in symbols]
                    for c in coins:
                        tf = c.timeframe.replace("m", "m").replace("h", "h").replace("d", "d")
                        streams.append(f"{c.symbol.lower()}@kline_{tf}")

                    logger_ws.info(
                        "🔗 [MONITOR] Connecting Binance WebSocket — %d symbols...",
                        len(symbols),
                    )
                    uri = (
                        f"wss://stream.binance.com:9443/stream"
                        f"?streams={'/'.join(streams)}"
                    )

                    async with websockets.connect(uri) as ws:
                        self._ws_connected = True
                        logger_ws.info(
                            "✅ [MONITOR] Connected. Watching: %s",
                            ", ".join(symbols),
                        )
                        last_analysis_time = datetime.now()
                        self._ws_last_msg_time = time.time()

                        while self.is_running:
                            # Check for new coins (hot reload)
                            async with AsyncSessionLocal() as check_session:
                                current_syms = [
                                    c.symbol
                                    for c in (
                                        await check_session.execute(
                                            select(TrackedCoin).where(
                                                TrackedCoin.enabled == True
                                            )
                                        )
                                    )
                                    .scalars()
                                    .all()
                                ]
                                if set(current_syms) != set(symbols):
                                    logger_ws.info(
                                        "🔄 [MONITOR] Coins changed (%d→%d), reconnecting...",
                                        len(symbols),
                                        len(current_syms),
                                    )
                                    break

                            try:
                                msg = await asyncio.wait_for(ws.recv(), timeout=5)
                                recv_time = time.time()
                                payload = json.loads(msg)
                                data = payload["data"]
                                symbol = data["s"]
                            except asyncio.TimeoutError:
                                continue

                            self._ws_msg_count += 1
                            self._ws_latency_ms = (time.time() - recv_time) * 1000

                            if "miniTicker" in payload["stream"]:
                                price = float(data["c"])
                                self.live_prices[symbol] = {
                                    "price": price,
                                    "time": datetime.now().strftime("%H:%M:%S"),
                                }
                                self._ws_last_msg_time = time.time()
                                self._ws_last_msg_desc = f"{symbol} ticker"
                                await self._check_live_trades(symbol, price)

                            elif "kline" in payload["stream"]:
                                k = data["k"]
                                self.live_klines[symbol] = {
                                    "t": k["t"],
                                    "o": float(k["o"]),
                                    "h": float(k["h"]),
                                    "l": float(k["l"]),
                                    "c": float(k["c"]),
                                    "v": float(k["v"]),
                                    "x": k["x"],
                                }
                                self._ws_last_msg_time = time.time()

                                if k["x"]:
                                    self._ws_last_msg_desc = f"{symbol} candle closed @ {k['c']}"
                                    logger_ws.info(
                                        "📊 [MONITOR] %s candle closed — price: %s",
                                        symbol,
                                        k["c"],
                                    )
                                    from Core.utils import safe_create_task
                                    safe_create_task(
                                        ai.analyze_and_trade(symbol),
                                        name=f"AI_Analyze_{symbol}",
                                    )
                                    last_analysis_time = datetime.now()

                            if "miniTicker" in payload["stream"] or k.get("x"):
                                self._save_data()

                            # Periodic full scan every 30 minutes
                            if (datetime.now() - last_analysis_time).seconds >= 1800:
                                api_calls = redis_client.get_data("binance_api_calls") or 0
                                logger_ws.info(
                                    "🔍 [SCANNER] Full scan — %d symbols | API: %d calls",
                                    len(symbols),
                                    api_calls,
                                )
                                from Core.utils import safe_create_task
                                for s in symbols:
                                    safe_create_task(
                                        ai.analyze_and_trade(s),
                                        name=f"AI_Scanner_{s}",
                                    )
                                    await asyncio.sleep(1.0)
                                last_analysis_time = datetime.now()
                                logger_ws.info("✨ [SCANNER] Periodic scan complete.")

                            self._emit_ws_diagnostics()

            except Exception as e:
                self._ws_connected = False
                self._ws_reconnect_attempts += 1
                logger_ws.warning(
                    "⚠️  [MONITOR] Connection error: %s | reconnect #%d",
                    e,
                    self._ws_reconnect_attempts,
                )
                await asyncio.sleep(5)

    async def _check_live_trades(self, symbol, price):
        """مراقبة الصفقات الحقيقية (Phase 4)"""
        async with AsyncSessionLocal() as session:
            res = await session.execute(
                select(LiveTrade).where(
                    (LiveTrade.symbol == symbol) & (LiveTrade.status == "OPEN")
                )
            )
            for trade in res.scalars().all():
                closed = False
                if trade.type == "BUY":
                    if price >= trade.take_profit:
                        trade.status, closed = "WON", True
                        trade.exit_reason = "Take Profit Hit"
                    elif price <= trade.stop_loss:
                        trade.status, closed = "LOST", True
                        trade.exit_reason = "Stop Loss Hit"
                elif trade.type == "SELL":
                    if price <= trade.take_profit:
                        trade.status, closed = "WON", True
                        trade.exit_reason = "Take Profit Hit"
                    elif price >= trade.stop_loss:
                        trade.status, closed = "LOST", True
                        trade.exit_reason = "Stop Loss Hit"

                if closed:
                    trade.exit_price = price
                    trade.closed_at = datetime.utcnow()
                    trade.duration = (trade.closed_at - trade.timestamp).seconds
                    if trade.type == "BUY":
                        pnl_pct = (
                            (price - trade.entry_price) / trade.entry_price
                        ) * 100
                    else:
                        pnl_pct = (
                            (trade.entry_price - price) / trade.entry_price
                        ) * 100
                    trade.pnl = (trade.amount * pnl_pct) / 100

                    # Capital Protection Engine
                    if trade.status == "LOST":
                        cfg_res = await session.execute(
                            select(UserConfig).where(
                                UserConfig.telegram_id == self.chat_id
                            )
                        )
                        cfg = cfg_res.scalars().first()
                        if cfg:
                            cfg.consecutive_losses += 1
                            if cfg.consecutive_losses >= 5:
                                cfg.emergency_stop = True
                                if self.bot:
                                    await self.bot.send_message(
                                        self.chat_id,
                                        "🚨 *EMERGENCY STOP*: 5 consecutive losses!",
                                    )
                    else:
                        cfg_res = await session.execute(
                            select(UserConfig).where(
                                UserConfig.telegram_id == self.chat_id
                            )
                        )
                        cfg = cfg_res.scalars().first()
                        if cfg:
                            cfg.consecutive_losses = 0

                    await session.commit()
                    if self.bot:
                        icon = "✅" if trade.status == "WON" else "❌"
                        await self.bot.send_message(
                            self.chat_id,
                            f"{icon} *Closed Trade*\n{symbol}: {trade.pnl:.2f} USDT",
                        )
