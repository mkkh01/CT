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
from Core.observability import Obs, Level, is_level

logger_ws = __import__("logging").getLogger("CT_Monitor")


class TradeMonitor:
    def __init__(self, bot=None):
        self.bot = bot
        self.chat_id = ADMIN_ID
        self.is_running = False
        self.live_prices = redis_client.get_data("live_prices") or {}
        self.live_klines = redis_client.get_data("live_klines") or {}

        # WebSocket stats
        self._ws_connected = False
        self._ws_reconnect_attempts = 0
        self._ws_last_msg_time: float = 0
        self._ws_msg_count: int = 0
        self._ws_last_msg_desc: str = ""
        self._ws_latency_ms: float = 0
        self._ws_last_symbols: list = []
        self._last_save: float = 0
        self._last_ws_diag: float = 0

    def _save_data(self):
        now = time.time()
        if now - self._last_save < 5:  # throttle saves to every 5s
            return
        self._last_save = now
        redis_client.set_data("live_prices", self.live_prices, ttl=3600)
        redis_client.set_data("live_klines", self.live_klines, ttl=3600)

    def _emit_ws_diagnostics(self):
        now = time.time()
        if now - self._last_ws_diag < 120:  # every 2 minutes
            return
        self._last_ws_diag = now

        Obs.binance_ws_status(
            connected=self._ws_connected,
            latency_ms=self._ws_latency_ms,
            symbols=len(self.live_prices),
            msg_count=int(self._ws_msg_count / max((now - self._started_at or 1) / 60, 1)),
        )

    async def check_prices(self):
        from Core.ai_engine import AIEngine
        ai = AIEngine(bot=self.bot)
        self.is_running = True
        self._started_at = time.time()
        Obs.event_log("TradeMonitor", "check_prices",
                      f"Institutional radar V4.0 — WebSocket Mode")

        while self.is_running:
            try:
                async with AsyncSessionLocal() as session:
                    coins_res = await session.execute(
                        select(TrackedCoin).where(TrackedCoin.enabled == True)
                    )
                    coins = coins_res.scalars().all()
                    symbols = [c.symbol for c in coins]

                    if not symbols:
                        await asyncio.sleep(15)
                        continue

                    self._ws_last_symbols = symbols

                    streams = [f"{s.lower()}@miniTicker" for s in symbols]
                    for c in coins:
                        tf = c.timeframe
                        streams.append(f"{c.symbol.lower()}@kline_{tf}")

                    uri = (
                        f"wss://stream.binance.com:9443/stream"
                        f"?streams={'/'.join(streams)}"
                    )

                    Obs.event_log("TradeMonitor", "ws_connect",
                                  f"{len(symbols)} symbols: {', '.join(symbols[:5])}"
                                  f"{'...' if len(symbols) > 5 else ''}")

                    async with websockets.connect(uri) as ws:
                        self._ws_connected = True
                        Obs.binance_ws_status(connected=True, symbols=len(symbols))
                        last_analysis_time = datetime.now()

                        while self.is_running:
                            # Hot reload check
                            async with AsyncSessionLocal() as cs:
                                cur = [c.symbol for c in
                                       (await cs.execute(
                                           select(TrackedCoin).where(
                                               TrackedCoin.enabled == True)))
                                       .scalars().all()]
                                if set(cur) != set(symbols):
                                    Obs.event_log("TradeMonitor", "hot_reload",
                                                  f"Coins changed: {len(symbols)}→{len(cur)}")
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
                            self._ws_last_msg_time = recv_time
                            stream = payload.get("stream", "")

                            # ── miniTicker → price stream ──
                            if "miniTicker" in stream:
                                price = float(data["c"])
                                self.live_prices[symbol] = {
                                    "price": price,
                                    "time": datetime.now().strftime("%H:%M:%S"),
                                }
                                self._ws_last_msg_desc = f"{symbol} ticker"

                                # Observability: price tick
                                Obs.price_tick(
                                    symbol=symbol, price=price,
                                    bid=float(data.get("b", 0)) if data.get("b") else None,
                                    ask=float(data.get("a", 0)) if data.get("a") else None,
                                    volume_24h=float(data.get("v", 0)) if data.get("v") else None,
                                    high_24h=float(data.get("h", 0)) if data.get("h") else None,
                                    low_24h=float(data.get("l", 0)) if data.get("l") else None,
                                )

                                await self._check_live_trades(symbol, price)

                            # ── kline → candle data ──
                            elif "kline" in stream:
                                k = data["k"]
                                o, h, l, c, v = float(k["o"]), float(k["h"]), float(k["l"]), float(k["c"]), float(k["v"])
                                is_closed = k["x"]

                                self.live_klines[symbol] = {
                                    "t": k["t"], "o": o, "h": h,
                                    "l": l, "c": c, "v": v, "x": is_closed,
                                }
                                self._ws_last_msg_desc = f"{symbol} kline_{k['i']}"

                                # Observability: candle
                                if is_closed:
                                    Obs.candle_received(
                                        symbol=symbol, timeframe=k["i"],
                                        open_p=o, high=h, low=l, close_p=c,
                                        volume=v, timestamp=k["t"],
                                        source="WebSocket",
                                        latency_ms=self._ws_latency_ms,
                                    )
                                    logger_ws.info("📊 %s candle closed @ %s", symbol, c)
                                    from Core.utils import safe_create_task
                                    safe_create_task(
                                        ai.analyze_and_trade(symbol),
                                        name=f"AI_Analyze_{symbol}",
                                    )
                                    last_analysis_time = datetime.now()

                            # Periodic save (throttled internally)
                            self._save_data()

                            # ── Periodic full scan every 30 min ──
                            if (datetime.now() - last_analysis_time).seconds >= 1800:
                                api_calls = redis_client.get_data("binance_api_calls") or 0
                                logger_ws.info("🔍 Scanning %d symbols | API: %d calls",
                                               len(symbols), api_calls)
                                from Core.utils import safe_create_task
                                for s in symbols:
                                    safe_create_task(
                                        ai.analyze_and_trade(s),
                                        name=f"AI_Scanner_{s}",
                                    )
                                    await asyncio.sleep(1.0)
                                last_analysis_time = datetime.now()
                                logger_ws.info("✨ Periodic scan complete.")

                            self._emit_ws_diagnostics()

            except Exception as e:
                self._ws_connected = False
                self._ws_reconnect_attempts += 1
                Obs.ws_reconnect(self._ws_reconnect_attempts, str(e)[:80])
                Obs.inc_ws_reconnects()
                await asyncio.sleep(5)

    async def _check_live_trades(self, symbol, price):
        """Monitor live trades — close on TP/SL hit."""
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

                if not closed:
                    # Debug: show distance to SL/TP
                    if is_level(Level.TRACE):
                        pnl_pct = ((price - trade.entry_price) / trade.entry_price) * 100 \
                            if trade.type == "BUY" else \
                            ((trade.entry_price - price) / trade.entry_price) * 100
                        Obs.trade_monitor(
                            trade_id=trade.id, symbol=symbol,
                            current_price=price, entry=trade.entry_price,
                            sl=trade.stop_loss, tp=trade.take_profit,
                            unrealized_pnl=trade.amount * pnl_pct / 100,
                        )
                    continue

                # Closed — calculate PnL
                trade.exit_price = price
                trade.closed_at = datetime.utcnow()
                trade.duration = (trade.closed_at - trade.timestamp).seconds
                if trade.type == "BUY":
                    pnl_pct = ((price - trade.entry_price) / trade.entry_price) * 100
                else:
                    pnl_pct = ((trade.entry_price - price) / trade.entry_price) * 100
                trade.pnl = (trade.amount * pnl_pct) / 100

                # Capital Protection Engine
                if trade.status == "LOST":
                    cfg_res = await session.execute(
                        select(UserConfig).where(UserConfig.telegram_id == self.chat_id)
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
                        select(UserConfig).where(UserConfig.telegram_id == self.chat_id)
                    )
                    cfg = cfg_res.scalars().first()
                    if cfg:
                        cfg.consecutive_losses = 0

                await session.commit()

                # Observability: trade closed
                Obs.trade_closed(
                    trade_id=trade.id, symbol=symbol,
                    direction=trade.type, entry=trade.entry_price,
                    exit_price=price, pnl=trade.pnl,
                    pnl_pct=pnl_pct, reason=trade.exit_reason,
                    duration_s=trade.duration,
                )

                # Telegram notification
                if self.bot:
                    icon = "✅" if trade.status == "WON" else "❌"
                    await self.bot.send_message(
                        self.chat_id,
                        f"{icon} *Closed Trade*\n{symbol}: {trade.pnl:.2f} USDT",
                    )
