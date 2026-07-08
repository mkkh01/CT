import asyncio
import json
import logging
import os
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

import pandas as pd
import websockets
from sqlalchemy import select

from config import ADMIN_ID
from database import AsyncSessionLocal, LiveTrade, TrackedCoin, UserConfig
from Core.redis_client import redis_client
from Core.observability import Obs
from Core.utils import safe_create_task

logger = logging.getLogger("CT_TradeMonitor")
logger_ws = logging.getLogger("CT_TradeMonitor_WS")


class TradeMonitor:
    def __init__(self, bot=None):
        self.bot = bot
        self.chat_id = ADMIN_ID
        self.is_running = False
        self.live_prices: Dict[str, Dict[str, Any]] = redis_client.get_data("live_prices") or {}
        self.live_klines: Dict[str, Dict[str, Any]] = redis_client.get_data("live_klines") or {}
        self._last_price_summary = 0.0
        self._last_snapshot = 0.0
        self._last_ws_heartbeat = 0.0

    def _save_data(self):
        redis_client.set_data("live_prices", self.live_prices, ttl=3600)
        redis_client.set_data("live_klines", self.live_klines, ttl=3600)

    async def _emit_heartbeat(self, symbols: List[str]):
        now = time.time()
        if now - self._last_ws_heartbeat < 30:
            return
        self._last_ws_heartbeat = now
        try:
            top = ", ".join(symbols[:5])
            Obs.system_snapshot(
                symbol=top,
                price=", ".join(
                    str(self.live_prices[s]["price"])
                    for s in symbols[:5]
                    if s in self.live_prices and "price" in self.live_prices[s]
                ),
                open_trades=len(redis_client.get_data("live_klines") or {}),
                api_calls=Obs.get().api_rest_count,
                uptime=now,
            )
        except Exception as exc:
            logger_ws.debug("heartbeat failed: %s", exc)

    async def check_prices(self):
        from Core.ai_engine import AIEngine

        ai = AIEngine(bot=self.bot, chat_id=self.chat_id)
        self.is_running = True
        logger.info("[MONITOR] Starting institutional radar — WebSocket mode")

        while self.is_running:
            try:
                async with AsyncSessionLocal() as session:
                    coins_res = await session.execute(select(TrackedCoin).where(TrackedCoin.enabled == True))
                    coins = coins_res.scalars().all()
                    symbols = [c.symbol for c in coins]

                if not symbols:
                    logger.info("[MONITOR] No enabled symbols yet; waiting for configuration...")
                    await asyncio.sleep(15)
                    continue

                streams = [f"{s.lower()}@miniTicker" for s in symbols]
                for c in coins:
                    streams.append(f"{c.symbol.lower()}@kline_{c.timeframe}")

                uri = f"wss://stream.binance.com:9443/stream?streams={'/'.join(streams)}"
                logger.info("[MONITOR] Connecting to Binance WS for %d symbols...", len(symbols))

                last_periodic_scan = time.time()
                async with websockets.connect(uri, ping_interval=20, ping_timeout=20) as ws:
                    logger.info("[MONITOR] Connected successfully — watching: %s", ", ".join(symbols))

                    while self.is_running:
                        async with AsyncSessionLocal() as check_session:
                            current_symbols = [
                                c.symbol
                                for c in (await check_session.execute(
                                    select(TrackedCoin).where(TrackedCoin.enabled == True)
                                )).scalars().all()
                            ]
                        if set(current_symbols) != set(symbols):
                            logger.info(
                                "[MONITOR] Symbol list changed (%d -> %d), reconnecting...",
                                len(symbols), len(current_symbols)
                            )
                            break

                        try:
                            msg = await asyncio.wait_for(ws.recv(), timeout=5)
                            payload = json.loads(msg)
                            data = payload["data"]
                            symbol = data["s"]
                            stream = payload.get("stream", "")
                        except asyncio.TimeoutError:
                            await self._emit_heartbeat(symbols)
                            continue

                        if "miniTicker" in stream:
                            price = float(data["c"])
                            self.live_prices[symbol] = {
                                "price": price,
                                "time": datetime.now().strftime("%H:%M:%S"),
                            }

                            Obs.price_tick(
                                symbol=symbol,
                                price=price,
                                bid=float(data.get("b", 0)) if data.get("b") else None,
                                ask=float(data.get("a", 0)) if data.get("a") else None,
                                volume_24h=float(data.get("v", 0)) if data.get("v") else None,
                                high_24h=float(data.get("h", 0)) if data.get("h") else None,
                                low_24h=float(data.get("l", 0)) if data.get("l") else None,
                            )

                            if time.time() - self._last_price_summary >= 60:
                                self._last_price_summary = time.time()
                                Obs.price_summary(symbol=symbol, price=price)

                            await self._check_live_trades(symbol, price)

                        elif "kline" in stream:
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

                            if k["x"]:
                                Obs.candle_received(
                                    symbol=symbol,
                                    timeframe=k["i"],
                                    open_p=float(k["o"]),
                                    high=float(k["h"]),
                                    low=float(k["l"]),
                                    close_p=float(k["c"]),
                                    volume=float(k["v"]),
                                    timestamp=k["t"],
                                    source="WebSocket",
                                    latency_ms=0,
                                )
                                logger.info("[MONITOR] %s candle closed @ %s", symbol, k["c"])
                                safe_create_task(
                                    ai.analyze_and_trade(symbol, source="WS_CANDLE"),
                                    name=f"AI_Analyze_{symbol}",
                                )
                                self._save_data()

                        # Run a real periodic scanner independently of candle events.
                        now = time.time()
                        if now - last_periodic_scan >= 1800:
                            try:
                                api_calls = redis_client.get_data("binance_api_calls") or 0
                                logger_ws.info("[SCAN] Scanning %d symbols | API calls=%d", len(symbols), api_calls)
                                for s in symbols:
                                    safe_create_task(
                                        ai.analyze_and_trade(s, source="SCANNER"),
                                        name=f"AI_Scanner_{s}",
                                    )
                                    await asyncio.sleep(1.0)
                                last_periodic_scan = now
                                logger_ws.info("[SCAN] Periodic scan complete.")
                            except Exception as scan_err:
                                logger_ws.error("[SCAN] Periodic scan failed: %s", scan_err)

                        if time.time() - self._last_snapshot >= 60:
                            self._last_snapshot = time.time()
                            self._save_data()

            except Exception as e:
                logger_ws.error("[MONITOR] Connection error: %s", e)
                await asyncio.sleep(5)

    async def _check_live_trades(self, symbol: str, price: float):
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

                if closed:
                    trade.exit_price = price
                    trade.closed_at = datetime.utcnow()
                    trade.duration = (trade.closed_at - trade.timestamp).seconds
                    pnl_pct = ((price - trade.entry_price) / trade.entry_price) * 100
                    trade.pnl = (trade.amount * pnl_pct) / 100

                    cfg_res = await session.execute(
                        select(UserConfig).where(UserConfig.telegram_id == self.chat_id)
                    )
                    cfg = cfg_res.scalars().first()
                    if cfg:
                        if trade.status == "LOST":
                            cfg.consecutive_losses += 1
                            if cfg.consecutive_losses >= 5:
                                cfg.emergency_stop = True
                                if self.bot:
                                    await self.bot.send_message(
                                        self.chat_id,
                                        "*EMERGENCY STOP*: 5 consecutive losses detected!",
                                        parse_mode="Markdown",
                                    )
                        else:
                            cfg.consecutive_losses = 0

                    await session.commit()
                    if self.bot:
                        icon = "✅" if trade.status == "WON" else "❌"
                        await self.bot.send_message(
                            self.chat_id,
                            f"{icon} *صفقة مغلقة*\n{symbol}: {trade.pnl:.2f} USDT",
                            parse_mode="Markdown",
                        )
