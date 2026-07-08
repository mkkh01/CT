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
from Core.observability import Obs, Level, is_level, _log

logger_ws = __import__("logging").getLogger("CT_Monitor")


class TradeMonitor:
    HEARTBEAT_KEY = "trade_monitor_heartbeat"
    WS_STATE_KEY = "ws_connection_state"

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
        self._last_price_summary: float = 0

    def _write_heartbeat(self, state: str, detail: str = ""):
        """كتابة نبضة حياة في Redis مع حالة الاتصال"""
        try:
            redis_client.set_data(self.HEARTBEAT_KEY, {
                "ts": time.time(),
                "iso": datetime.utcnow().isoformat(),
                "state": state,  # "starting", "connected", "disconnected", "error", "stopped"
                "detail": detail,
                "symbols_count": len(self._ws_last_symbols),
                "msg_count": self._ws_msg_count,
                "reconnects": self._ws_reconnect_attempts,
            }, ttl=60)
        except Exception as e:
            logger_ws.error(f"[HEARTBEAT] Failed to write: {e}")

    def _save_data(self, force: bool = False):
        now = time.time()
        if not force and now - self._last_save < 5:
            return
        self._last_save = now
        try:
            redis_client.set_data("live_prices", self.live_prices, ttl=3600)
            redis_client.set_data("live_klines", self.live_klines, ttl=3600)
            self._write_heartbeat("connected" if self._ws_connected else "disconnected")
        except Exception as e:
            logger_ws.error(f"[SAVE] Failed to persist prices: {e}")

    def _emit_ws_diagnostics(self):
        now = time.time()
        if now - self._last_ws_diag < 120:
            return
        self._last_ws_diag = now

        try:
            Obs.binance_ws_status(
                connected=self._ws_connected,
                latency_ms=self._ws_latency_ms,
                symbols=len(self.live_prices),
                msg_count=int(self._ws_msg_count / max((now - self._started_at or 1) / 60, 1)),
            )
        except Exception as e:
            logger_ws.error(f"[DIAG] WS diagnostics failed: {e}")

    async def check_prices(self):
        """الحلقة الرئيسية مع ضمان عدم الموت بصمت"""
        self._write_heartbeat("starting", "AIEngine initializing...")
        self.is_running = True
        self._started_at = time.time()

        Obs.event_log("TradeMonitor", "check_prices",
                      f"Institutional radar V4.0 — WebSocket Mode")

        await asyncio.sleep(1)

        while self.is_running:
            try:
                try:
                    from Core.ai_engine import AIEngine
                    ai = AIEngine(bot=self.bot)
                except Exception as ai_err:
                    logger_ws.critical(f"[AIEngine] Import/init failed: {ai_err}")
                    self._write_heartbeat("error", f"AIEngine init failed: {ai_err}")
                    await asyncio.sleep(30)
                    continue

                try:
                    async with AsyncSessionLocal() as session:
                        coins_res = await session.execute(
                            select(TrackedCoin).where(TrackedCoin.enabled == True)
                        )
                        coins = coins_res.scalars().all()
                        symbols = [c.symbol for c in coins]
                except Exception as db_err:
                    logger_ws.error(f"[DB] Failed to fetch coins: {db_err}")
                    self._write_heartbeat("error", f"DB query failed: {db_err}")
                    await asyncio.sleep(30)
                    continue

                if not symbols:
                    _log(f"  [MONITOR] ℹ️  لا توجد عملات مفعلة — أضف عملة من بوت تلجرام (➕ إضافة عملة)")
                    self._write_heartbeat("disconnected", "No enabled coins")
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

                self._write_heartbeat("starting", f"Connecting to WS for {len(symbols)} symbols")

                try:
                    async with websockets.connect(uri, ping_interval=20, ping_timeout=60) as ws:
                        self._ws_connected = True
                        self._ws_reconnect_attempts = 0
                        self._write_heartbeat("connected", f"WS open, {len(symbols)} symbols")
                        Obs.binance_ws_status(connected=True, symbols=len(symbols))
                        last_analysis_time = datetime.now()
                        tick_count_since_save = 0

                        while self.is_running:
                            try:
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
                            except Exception as hr_err:
                                logger_ws.warning(f"[HOT_RELOAD] DB check failed: {hr_err}")

                            try:
                                msg = await asyncio.wait_for(ws.recv(), timeout=5)
                                recv_time = time.time()
                                payload = json.loads(msg)
                                data = payload["data"]
                                symbol = data["s"]
                            except asyncio.TimeoutError:
                                continue
                            except json.JSONDecodeError as json_err:
                                logger_ws.error(f"[WS] Invalid JSON: {json_err}")
                                continue
                            except Exception as recv_err:
                                logger_ws.error(f"[WS] Receive error: {recv_err}")
                                break

                            self._ws_msg_count += 1
                            self._ws_latency_ms = (time.time() - recv_time) * 1000
                            self._ws_last_msg_time = recv_time
                            stream = payload.get("stream", "")

                            if "miniTicker" in stream:
                                price = float(data["c"])
                                self.live_prices[symbol] = {
                                    "price": price,
                                    "time": datetime.now().strftime("%H:%M:%S"),
                                }
                                self._ws_last_msg_desc = f"{symbol} ticker"
                                tick_count_since_save += 1

                                try:
                                    Obs.price_tick(
                                        symbol=symbol, price=price,
                                        bid=float(data.get("b", 0)) if data.get("b") else None,
                                        ask=float(data.get("a", 0)) if data.get("a") else None,
                                        volume_24h=float(data.get("v", 0)) if data.get("v") else None,
                                        high_24h=float(data.get("h", 0)) if data.get("h") else None,
                                        low_24h=float(data.get("l", 0)) if data.get("l") else None,
                                    )
                                except Exception as obs_err:
                                    logger_ws.error(f"[OBS] price_tick failed: {obs_err}")

                                now = time.time()
                                if now - self._last_price_summary >= 60:
                                    self._last_price_summary = now
                                    try:
                                        Obs.price_summary(symbol=symbol, price=price)
                                    except Exception as ps_err:
                                        logger_ws.error(f"[OBS] price_summary failed: {ps_err}")

                                if tick_count_since_save >= 100 or (now - self._last_save) >= 5:
                                    self._save_data()
                                    tick_count_since_save = 0

                                try:
                                    await self._check_live_trades(symbol, price)
                                except Exception as lt_err:
                                    logger_ws.error(f"[LIVE_TRADES] Check failed: {lt_err}")

                            elif "kline" in stream:
                                k = data["k"]
                                o, h, l, c, v = float(k["o"]), float(k["h"]), float(k["l"]), float(k["c"]), float(k["v"])
                                is_closed = k["x"]

                                self.live_klines[symbol] = {
                                    "t": k["t"], "o": o, "h": h,
                                    "l": l, "c": c, "v": v, "x": is_closed,
                                }
                                self._ws_last_msg_desc = f"{symbol} kline_{k['i']}"

                                if is_closed:
                                    try:
                                        Obs.candle_received(
                                            symbol=symbol, timeframe=k["i"],
                                            open_p=o, high=h, low=l, close_p=c,
                                            volume=v, timestamp=k["t"],
                                            source="WebSocket",
                                            latency_ms=self._ws_latency_ms,
                                        )
                                    except Exception as obs_err:
                                        logger_ws.error(f"[OBS] candle_received failed: {obs_err}")

                                    logger_ws.info("📊 %s candle closed @ %s", symbol, c)
                                    from Core.utils import safe_create_task
                                    safe_create_task(
                                        ai.analyze_and_trade(symbol),
                                        name=f"AI_Analyze_{symbol}",
                                    )
                                    last_analysis_time = datetime.now()

                            self._save_data()

                            if (datetime.now() - last_analysis_time).seconds >= 1800:
                                try:
                                    api_calls = redis_client.get_data("binance_api_calls") or 0
                                    logger_ws.info("🔍 Scanning %d symbols | API: %d calls",
                                                   len(symbols), api_calls)
                                    for s in symbols:
                                        safe_create_task(
                                            ai.analyze_and_trade(s),
                                            name=f"AI_Scanner_{s}",
                                        )
                                        await asyncio.sleep(1.0)
                                    last_analysis_time = datetime.now()
                                    logger_ws.info("✨ Periodic scan complete.")
                                except Exception as scan_err:
                                    logger_ws.error(f"[SCAN] Periodic scan failed: {scan_err}")

                            self._emit_ws_diagnostics()

                except websockets.exceptions.InvalidURI as uri_err:
                    logger_ws.critical(f"[WS] Invalid URI: {uri_err}")
                    self._write_heartbeat("error", f"Invalid WS URI: {uri_err}")
                    await asyncio.sleep(60)
                except Exception as ws_err:
                    logger_ws.error(f"[WS] Connection error: {ws_err}")
                    self._write_heartbeat("error", f"WS connection error: {ws_err}")

            except Exception as e:
                self._ws_connected = False
                self._ws_reconnect_attempts += 1
                try:
                    Obs.ws_reconnect(self._ws_reconnect_attempts, str(e)[:80])
                    Obs.inc_ws_reconnects()
                except Exception:
                    pass
                self._write_heartbeat("error", f"Outer loop exception: {str(e)[:200]}")
                logger_ws.error(f"[MONITOR] Outer loop exception: {e}", exc_info=True)
                await asyncio.sleep(5)

        self._write_heartbeat("stopped", "Monitor loop exited")
        logger_ws.info("[MONITOR] check_prices loop exited.")

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
                    if is_level(Level.TRACE):
                        pnl_pct = ((price - trade.entry_price) / trade.entry_price) * 100                             if trade.type == "BUY" else                             ((trade.entry_price - price) / trade.entry_price) * 100
                        try:
                            Obs.trade_monitor(
                                trade_id=trade.id, symbol=symbol,
                                current_price=price, entry=trade.entry_price,
                                sl=trade.stop_loss, tp=trade.take_profit,
                                unrealized_pnl=trade.amount * pnl_pct / 100,
                            )
                        except Exception:
                            pass
                    continue

                trade.exit_price = price
                trade.closed_at = datetime.utcnow()
                trade.duration = (trade.closed_at - trade.timestamp).seconds
                if trade.type == "BUY":
                    pnl_pct = ((price - trade.entry_price) / trade.entry_price) * 100
                else:
                    pnl_pct = ((trade.entry_price - price) / trade.entry_price) * 100
                trade.pnl = (trade.amount * pnl_pct) / 100

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

                try:
                    Obs.trade_closed(
                        trade_id=trade.id, symbol=symbol,
                        direction=trade.type, entry=trade.entry_price,
                        exit_price=price, pnl=trade.pnl,
                        pnl_pct=pnl_pct, reason=trade.exit_reason,
                        duration_s=trade.duration,
                    )
                except Exception:
                    pass

                if self.bot:
                    icon = "✅" if trade.status == "WON" else "❌"
                    try:
                        await self.bot.send_message(
                            self.chat_id,
                            f"{icon} *Closed Trade*\n{symbol}: {trade.pnl:.2f} USDT",
                        )
                    except Exception as tg_err:
                        logger_ws.error(f"[TG] Failed to send trade close: {tg_err}")
