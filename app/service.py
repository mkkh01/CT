from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

from .analysis import AnalysisEngine
from .config import Settings
from .market import BinanceMarketData
from .models import AnalysisSnapshot, Candle, NoTrade, Signal, Trade, utc_now
from .storage import RedisStore, SupabaseStore

logger = logging.getLogger(__name__)

TERMINAL_STATUSES = {"TP1_HIT", "TP2_HIT", "SL_HIT", "INVALIDATED", "EXPIRED", "CANCELLED"}
ACTIVE_STATUSES = {"SIGNAL_CONFIRMED", "ENTRY_PENDING", "ACTIVE"}
COMPLETED_STATUSES = TERMINAL_STATUSES
SYMBOL_NAMES = {
    "BTCUSDT": "Bitcoin",
    "ETHUSDT": "Ethereum",
    "BNBUSDT": "BNB",
    "SOLUSDT": "Solana",
    "XRPUSDT": "XRP",
    "ADAUSDT": "Cardano",
    "DOGEUSDT": "Dogecoin",
    "AVAXUSDT": "Avalanche",
    "LINKUSDT": "Chainlink",
    "DOTUSDT": "Polkadot",
    "TRXUSDT": "TRON",
    "LTCUSDT": "Litecoin",
    "BCHUSDT": "Bitcoin Cash",
    "NEARUSDT": "NEAR Protocol",
    "UNIUSDT": "Uniswap",
    "ATOMUSDT": "Cosmos",
    "ETCUSDT": "Ethereum Classic",
    "FILUSDT": "Filecoin",
    "APTUSDT": "Aptos",
    "ARBUSDT": "Arbitrum",
}


class IndicatorService:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.analysis_engine = AnalysisEngine(settings)
        self.storage = SupabaseStore(settings)
        self.redis = RedisStore(settings)
        self.market = BinanceMarketData(settings, on_candle=self.on_candle, on_candle_closed=self.on_candle_closed)
        self.started = False
        self.starting = False
        self.started_at: str | None = None
        self.last_analysis_at: str | None = None
        self.last_signal_at: str | None = None
        self.cycle_count = 0
        self.signal_count = 0
        self._analysis: dict[str, AnalysisSnapshot] = {}
        self._signals: dict[str, Signal] = {}
        self._trades: dict[str, Trade] = {}
        self._latest_prices: dict[str, dict[str, Any]] = {}
        self._analysis_lock = asyncio.Lock()
        self._subscribers: set[asyncio.Queue] = set()

    async def start(self) -> None:
        if self.started or self.starting:
            return
        self.starting = True
        try:
            await self.storage.startup()
            await self.redis.startup()
            if self.storage.enabled:
                await self.storage.ping()
                await self._restore_active_trades()
            if not self.settings.disable_auto_start:
                await self.market.start()
            self.started = True
            self.started_at = utc_now()
        finally:
            self.starting = False

    async def _restore_active_trades(self) -> None:
        try:
            rows = await self.storage.list_trades(active_only=True, limit=500)
            for row in rows:
                trade = Trade.from_dict(row)
                self._trades[trade.id] = trade
                signal_payload = trade.payload.get("signal") if isinstance(trade.payload, dict) else None
                if isinstance(signal_payload, dict):
                    self._signals[trade.signal_id] = Signal.from_dict(signal_payload)
            self.signal_count = len(self._signals)
            logger.info("active_trades_restored count=%s", len(self._trades))
        except Exception as exc:
            logger.warning("active_trades_restore_failed error=%s", exc)

    async def stop(self) -> None:
        await self.market.stop()
        await self.redis.close()
        await self.storage.close()
        self.started = False

    def subscribe(self) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=200)
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        self._subscribers.discard(queue)

    async def _broadcast(self, event: dict[str, Any]) -> None:
        for queue in list(self._subscribers):
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
                try:
                    queue.put_nowait(event)
                except asyncio.QueueFull:
                    pass

    async def on_candle(self, candle: Candle) -> None:
        key = f"{candle.symbol}:{candle.timeframe}"
        previous = self._latest_prices.get(key, {}).get("price")
        self._latest_prices[key] = {
            "symbol": candle.symbol, "timeframe": candle.timeframe, "price": candle.close,
            "previous_price": previous, "received_at": candle.received_at,
            "open_time": candle.open_time, "is_closed": candle.is_closed,
        }
        await self._broadcast({"type": "candle", "payload": candle.to_dict(), "current_price": candle.close})
        for trade in self._trades.values():
            if trade.symbol == candle.symbol and trade.timeframe == candle.timeframe and trade.status in ACTIVE_STATUSES:
                trade.last_price = candle.close
                await self._broadcast({"type": "trade", "payload": trade.to_dict()})

    async def on_candle_closed(self, candle: Candle) -> None:
        if self.storage.enabled:
            await self.storage.upsert_candle(candle)
        await self._update_signal_lifecycle(candle)
        if candle.timeframe not in self.settings.analysis_timeframes:
            return
        self.cycle_count += 1
        is_entry_timeframe = candle.timeframe == self.settings.entry_timeframe
        snapshot, result = await self.analyze(candle.symbol, candle.timeframe, create_signal=is_entry_timeframe)
        await self._broadcast({"type": "analysis", "payload": {**snapshot.to_dict(), "result": result.to_dict()}})
        if is_entry_timeframe and isinstance(result, Signal):
            await self._broadcast({"type": "signal", "payload": result.to_dict()})

    def _trade_from_signal(self, signal: Signal) -> Trade:
        return Trade(
            id=signal.id, signal_id=signal.id, symbol=signal.symbol, timeframe=signal.timeframe,
            direction=signal.direction, status=signal.status, score=signal.score, entry=signal.entry,
            stop_loss=signal.stop_loss, tp1=signal.tp1, tp2=signal.tp2, created_at=signal.created_at,
            reasons=list(signal.reasons), payload={"signal": signal.to_dict()},
        )

    @staticmethod
    def _close_reason(status: str) -> str:
        return {
            "TP1_HIT": "TP1_REACHED",
            "TP2_HIT": "TP2_REACHED_LEGACY",
            "SL_HIT": "STOP_LOSS_REACHED",
            "EXPIRED": "ENTRY_NOT_REACHED_WITHIN_MAX_PENDING_CANDLES",
            "INVALIDATED": "SIGNAL_INVALIDATED",
            "CANCELLED": "SIGNAL_CANCELLED",
        }.get(status, status)

    async def _update_signal_lifecycle(self, candle: Candle) -> None:
        changed_signals: list[Signal] = []
        changed_trades: list[Trade] = []
        for signal in list(self._signals.values()):
            if signal.symbol != candle.symbol or signal.timeframe != candle.timeframe or signal.status in TERMINAL_STATUSES:
                continue
            trade = self._trades.get(signal.id)
            if not trade:
                trade = self._trade_from_signal(signal)
                self._trades[trade.id] = trade
            trade.last_price = candle.close
            trade.last_candle_open_time = candle.open_time
            status_before = trade.status
            created_open = int(signal.metadata.get("entry_open_time", signal.metadata.get("created_open_time", candle.open_time)))
            age = max(0, candle.open_time - created_open)
            interval = max(1, candle.close_time - candle.open_time)

            if trade.status in {"SIGNAL_CONFIRMED", "ENTRY_PENDING"}:
                reached_entry = candle.low <= signal.entry <= candle.high
                if reached_entry:
                    trade.status = signal.status = "ACTIVE"
                    trade.activated_at = trade.activated_at or utc_now()
                elif age >= self.settings.max_pending_candles * interval:
                    trade.status = signal.status = "EXPIRED"
                    trade.exit_at = utc_now()
                    trade.close_reason = self._close_reason("EXPIRED")

            if trade.status == "ACTIVE":
                if signal.direction == "BUY":
                    stop_hit = candle.low <= signal.stop_loss
                    tp1_hit = candle.high >= signal.tp1
                else:
                    stop_hit = candle.high >= signal.stop_loss
                    tp1_hit = candle.low <= signal.tp1
                both_stop_and_target = stop_hit and tp1_hit
                if stop_hit:
                    trade.status = signal.status = "SL_HIT"
                    trade.exit_at = utc_now()
                    trade.exit_price = signal.stop_loss
                    trade.close_reason = "STOP_LOSS_REACHED_CONSERVATIVE_INTRABAR_PRIORITY" if both_stop_and_target else self._close_reason("SL_HIT")
                elif tp1_hit:
                    trade.status = signal.status = "TP1_HIT"
                    trade.exit_at = utc_now()
                    trade.exit_price = signal.tp1
                    trade.tp1_hit_at = trade.tp1_hit_at or trade.exit_at
                    trade.close_reason = self._close_reason("TP1_HIT")

            if status_before != trade.status or trade.status in ACTIVE_STATUSES or trade.status in TERMINAL_STATUSES:
                signal.metadata.update({
                    "last_price": trade.last_price, "last_candle_open_time": trade.last_candle_open_time,
                    "exit_price": trade.exit_price, "exit_at": trade.exit_at, "close_reason": trade.close_reason,
                })
                trade.payload["signal"] = signal.to_dict()
                changed_signals.append(signal)
                changed_trades.append(trade)

        for signal, trade in zip(changed_signals, changed_trades):
            if self.storage.enabled:
                await self.storage.update_signal_status(signal)
                await self.storage.update_trade(trade)
            await self.redis.set_json(f"signal:{signal.symbol}:{signal.timeframe}", signal.to_dict(), ttl=86400)
            await self._broadcast({"type": "trade", "payload": trade.to_dict()})

    async def analyze(self, symbol: str, timeframe: str | None = None, create_signal: bool | None = None) -> tuple[AnalysisSnapshot, Signal | NoTrade]:
        symbol = symbol.upper()
        timeframe = (timeframe or self.settings.entry_timeframe).lower()
        if create_signal is None:
            create_signal = timeframe == self.settings.entry_timeframe
        mapping = self.settings.mtf_mapping.get(timeframe, [self.settings.structure_timeframe, self.settings.htf_timeframe])
        structure_timeframe, htf_timeframe = mapping[0], mapping[1]
        await self.market.ensure_history(symbol, timeframe)
        await self.market.ensure_history(symbol, structure_timeframe)
        await self.market.ensure_history(symbol, htf_timeframe)
        entry_raw = await self.market.snapshot(symbol, timeframe)
        structure_raw = await self.market.snapshot(symbol, structure_timeframe)
        htf_raw = await self.market.snapshot(symbol, htf_timeframe)
        entry = [candle for candle in entry_raw if candle.is_closed]
        structure = [candle for candle in structure_raw if candle.is_closed]
        htf = [candle for candle in htf_raw if candle.is_closed]
        snapshot, result = self.analysis_engine.analyze(symbol, timeframe, entry, structure, htf, data_fresh=self._data_fresh())
        if isinstance(result, Signal) and not create_signal:
            snapshot.decision = "NO TRADE"
            snapshot.reasons = list(dict.fromkeys([*snapshot.reasons, "CONTEXT_ONLY_FRAME"]))
            result = NoTrade(symbol, timeframe, reasons=["CONTEXT_ONLY_FRAME"], score=result.score)
        key = f"{symbol}:{timeframe}"
        self._analysis[key] = snapshot
        self.last_analysis_at = utc_now()
        await self.redis.set_json(f"analysis:{symbol}:{timeframe}", snapshot.to_dict(), ttl=900)
        if self.storage.enabled:
            await self.storage.upsert_analysis(snapshot)
        if isinstance(result, Signal) and create_signal:
            async with self._analysis_lock:
                conflicting = any(
                    item.symbol == result.symbol and item.timeframe == result.timeframe and item.direction != result.direction and item.status in ACTIVE_STATUSES
                    for item in self._signals.values()
                )
                if conflicting:
                    snapshot.decision = "NO TRADE"
                    snapshot.reasons.append("CONFLICTING ACTIVE SIGNAL")
                    result = NoTrade(result.symbol, result.timeframe, reasons=["CONFLICTING ACTIVE SIGNAL"], score=result.score)
                elif result.id not in self._signals:
                    self._signals[result.id] = result
                    trade = self._trade_from_signal(result)
                    self._trades[trade.id] = trade
                    self.signal_count += 1
                    self.last_signal_at = result.created_at
                    await self.redis.set_json(f"signal:{symbol}:{timeframe}", result.to_dict(), ttl=86400)
                    if self.storage.enabled:
                        await self.storage.insert_signal(result)
                        await self.storage.insert_trade(trade)
                    await self._broadcast({"type": "trade", "payload": trade.to_dict()})
        return snapshot, result

    def _data_fresh(self) -> bool:
        if not self.market.last_message_at:
            return False
        if self.storage.enabled and (not self.storage.last_success_at or self.storage.last_error):
            return False
        try:
            last = datetime.fromisoformat(self.market.last_message_at)
            return (datetime.now(timezone.utc) - last).total_seconds() <= self.settings.stale_data_seconds
        except ValueError:
            return False

    async def get_candles(self, symbol: str, timeframe: str, limit: int = 200) -> list[dict[str, Any]]:
        await self.market.ensure_history(symbol.upper(), timeframe.lower())
        candles = await self.market.snapshot(symbol.upper(), timeframe.lower())
        return [item.to_dict() for item in candles[-min(max(limit, 1), self.settings.history_limit):]]

    async def get_analysis(self, symbol: str, timeframe: str | None = None) -> dict[str, Any]:
        key = f"{symbol.upper()}:{(timeframe or self.settings.entry_timeframe).lower()}"
        if key not in self._analysis:
            snapshot, result = await self.analyze(symbol.upper(), timeframe)
            data = snapshot.to_dict()
            data["result"] = result.to_dict()
            return data
        snapshot = self._analysis[key]
        data = snapshot.to_dict()
        candidates = [item for item in self._signals.values() if item.symbol == snapshot.symbol and item.timeframe == snapshot.timeframe and item.status in ACTIVE_STATUSES]
        signal = max(candidates, key=lambda item: item.created_at, default=None)
        data["result"] = signal.to_dict() if signal else {"decision": "NO TRADE", "reasons": snapshot.reasons, "score": max(snapshot.bullish_score, snapshot.bearish_score)}
        return data

    async def get_signals(self, symbol: str, timeframe: str, limit: int = 50) -> list[dict[str, Any]]:
        local = [item.to_dict() for item in self._signals.values() if item.symbol == symbol.upper() and item.timeframe == timeframe.lower()]
        if local:
            return sorted(local, key=lambda item: item["created_at"], reverse=True)[:limit]
        if self.storage.enabled:
            return await self.storage.list_signals(symbol.upper(), timeframe.lower(), limit)
        return []

    async def get_trades(self, symbol: str | None = None, timeframe: str | None = None, limit: int = 100, active_only: bool = False, completed_only: bool = False) -> list[dict[str, Any]]:
        local = list(self._trades.values())
        if symbol:
            local = [item for item in local if item.symbol == symbol.upper()]
        if timeframe:
            local = [item for item in local if item.timeframe == timeframe.lower()]
        if active_only:
            local = [item for item in local if item.status in ACTIVE_STATUSES]
        if completed_only:
            local = [item for item in local if item.status in COMPLETED_STATUSES]
        local_by_id = {item.id: item for item in local}
        if self.storage.enabled:
            stored = await self.storage.list_trades(symbol, timeframe, limit, active_only=active_only)
            for row in stored:
                try:
                    trade = Trade.from_dict(row)
                except (KeyError, TypeError, ValueError):
                    continue
                if active_only and trade.status not in ACTIVE_STATUSES:
                    continue
                if completed_only and trade.status not in COMPLETED_STATUSES:
                    continue
                local_by_id.setdefault(trade.id, trade)
        rows = sorted(local_by_id.values(), key=lambda item: item.created_at, reverse=True)
        return [item.to_dict() for item in rows[:min(max(limit, 1), 500)]]

    async def get_active_signal_summary(self) -> list[dict[str, Any]]:
        grouped: dict[str, list[dict[str, Any]]] = {}
        for signal in self._signals.values():
            if signal.status in ACTIVE_STATUSES:
                grouped.setdefault(signal.symbol, []).append(signal.to_dict())
        return [
            {"symbol": symbol, "name": SYMBOL_NAMES.get(symbol, symbol), "count": len(items), "signals": sorted(items, key=lambda item: item["created_at"], reverse=True)}
            for symbol, items in sorted(grouped.items())
        ]

    async def get_successful_trade_summary(self, limit: int = 500) -> list[dict[str, Any]]:
        trades = await self.get_trades(limit=limit, completed_only=True)
        grouped: dict[str, list[dict[str, Any]]] = {}
        for trade in trades:
            if trade.get("status") == "TP1_HIT":
                grouped.setdefault(str(trade["symbol"]), []).append(trade)
        return [
            {"symbol": symbol, "name": SYMBOL_NAMES.get(symbol, symbol), "count": len(items), "trades": sorted(items, key=lambda item: item["created_at"], reverse=True)}
            for symbol, items in sorted(grouped.items())
        ]

    def status(self) -> dict[str, Any]:
        return {
            "status": "ok", "app_version": self.settings.app_version, "config_version": self.settings.config_version,
            "started": self.started, "starting": self.starting, "started_at": self.started_at,
            "execution_mode": "paper", "cycle_count": self.cycle_count, "signal_count": self.signal_count,
            "trade_count": len(self._trades), "active_trade_count": sum(item.status in ACTIVE_STATUSES for item in self._trades.values()),
            "last_analysis_at": self.last_analysis_at, "last_signal_at": self.last_signal_at,
            "latest_prices": self._latest_prices, "subscriber_count": len(self._subscribers),
            "market": self.market.status(),
            "integrations": {"supabase_configured": self.storage.enabled, "redis_configured": bool(self.redis.url), "supabase_connected": bool(self.storage.last_success_at and not self.storage.last_error), "supabase_last_success_at": self.storage.last_success_at, "supabase_last_error": self.storage.last_error, "redis_connected": self.redis.enabled},
            "settings": {"symbols": self.settings.symbols, "entry_timeframe": self.settings.entry_timeframe, "analysis_timeframes": self.settings.analysis_timeframes, "stream_timeframes": self.settings.stream_timeframes, "structure_timeframe": self.settings.structure_timeframe, "htf_timeframe": self.settings.htf_timeframe, "min_signal_score": self.settings.min_signal_score},
        }
