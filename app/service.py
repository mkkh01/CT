from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

from .analysis import AnalysisEngine
from .config import Settings
from .market import BinanceMarketData
from .models import AnalysisSnapshot, Candle, NoTrade, Signal
from .storage import RedisStore, SupabaseStore

logger = logging.getLogger(__name__)


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
        self._signal_lock = asyncio.Lock()
        self._subscribers: set[asyncio.Queue] = set()

    async def start(self) -> None:
        if self.started or self.starting:
            return
        self.starting = True
        try:
            await self.storage.startup()
            await self.redis.startup()
            if not self.settings.disable_auto_start:
                await self.market.start()
            self.started = True
            self.started_at = datetime.now(timezone.utc).isoformat()
        finally:
            self.starting = False

    async def stop(self) -> None:
        await self.market.stop()
        await self.redis.close()
        await self.storage.close()
        self.started = False

    def subscribe(self) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=100)
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
        await self._broadcast({"type": "candle", "payload": candle.to_dict()})

    async def on_candle_closed(self, candle: Candle) -> None:
        if candle.timeframe not in self.settings.analysis_timeframes:
            return
        self.cycle_count += 1
        if self.storage.enabled:
            await self.storage.upsert_candle(candle)
        await self._update_signal_lifecycle(candle)
        snapshot, result = await self.analyze(candle.symbol, candle.timeframe)
        await self._broadcast({"type": "analysis", "payload": {**snapshot.to_dict(), "result": result.to_dict()}})
        if isinstance(result, Signal):
            await self._broadcast({"type": "signal", "payload": result.to_dict()})

    async def _update_signal_lifecycle(self, candle: Candle) -> None:
        changed: list[Signal] = []
        for signal in list(self._signals.values()):
            if signal.symbol != candle.symbol or signal.timeframe != candle.timeframe:
                continue
            if signal.status in {"TP1_HIT", "TP2_HIT", "SL_HIT", "INVALIDATED", "EXPIRED", "CANCELLED"}:
                continue
            created_open = int(signal.metadata.get("entry_open_time", signal.metadata.get("created_open_time", candle.open_time)))
            age = max(0, candle.open_time - created_open)
            interval = max(1, candle.close_time - candle.open_time)
            if signal.status in {"SIGNAL_CONFIRMED", "ENTRY_PENDING"}:
                if signal.direction == "BUY" and candle.low <= signal.entry <= candle.high:
                    signal.status = "ACTIVE"
                elif signal.direction == "SELL" and candle.low <= signal.entry <= candle.high:
                    signal.status = "ACTIVE"
                elif age > self.settings.max_pending_candles * interval:
                    signal.status = "EXPIRED"
            if signal.status == "ACTIVE":
                if signal.direction == "BUY":
                    if candle.low <= signal.stop_loss:
                        signal.status = "SL_HIT"
                    elif candle.high >= signal.tp2:
                        signal.status = "TP2_HIT"
                    elif candle.high >= signal.tp1:
                        signal.status = "TP1_HIT"
                else:
                    if candle.high >= signal.stop_loss:
                        signal.status = "SL_HIT"
                    elif candle.low <= signal.tp2:
                        signal.status = "TP2_HIT"
                    elif candle.low <= signal.tp1:
                        signal.status = "TP1_HIT"
            if signal.status != "SIGNAL_CONFIRMED":
                changed.append(signal)
        for signal in changed:
            if self.storage.enabled:
                await self.storage.update_signal_status(signal)
            await self.redis.set_json(f"signal:{signal.symbol}:{signal.timeframe}", signal.to_dict(), ttl=86400)

    async def analyze(self, symbol: str, timeframe: str | None = None) -> tuple[AnalysisSnapshot, Signal | NoTrade]:
        timeframe = (timeframe or self.settings.entry_timeframe).lower()
        mapping = self.settings.mtf_mapping.get(timeframe, [self.settings.structure_timeframe, self.settings.htf_timeframe])
        structure_timeframe, htf_timeframe = mapping[0], mapping[1]
        await self.market.ensure_history(symbol, timeframe)
        await self.market.ensure_history(symbol, structure_timeframe)
        await self.market.ensure_history(symbol, htf_timeframe)
        entry = await self.market.snapshot(symbol, timeframe)
        structure = await self.market.snapshot(symbol, structure_timeframe)
        htf = await self.market.snapshot(symbol, htf_timeframe)
        snapshot, result = self.analysis_engine.analyze(symbol, timeframe, entry, structure, htf, data_fresh=self._data_fresh())
        key = f"{symbol}:{timeframe}"
        self._analysis[key] = snapshot
        self.last_analysis_at = datetime.now(timezone.utc).isoformat()
        await self.redis.set_json(f"analysis:{symbol}:{timeframe}", snapshot.to_dict(), ttl=900)
        if self.storage.enabled:
            await self.storage.upsert_analysis(snapshot)
        if isinstance(result, Signal):
            async with self._signal_lock:
                conflicting = any(item.symbol == result.symbol and item.timeframe == result.timeframe and item.direction != result.direction and item.status in {"SIGNAL_CONFIRMED", "ENTRY_PENDING", "ACTIVE"} for item in self._signals.values())
                if conflicting:
                    snapshot.decision = "NO TRADE"
                    snapshot.reasons.append("CONFLICTING ACTIVE SIGNAL")
                    result = NoTrade(result.symbol, result.timeframe, reasons=["CONFLICTING ACTIVE SIGNAL"], score=result.score)
                elif result.id not in self._signals:
                    self._signals[result.id] = result
                    self.signal_count += 1
                    self.last_signal_at = result.created_at
                    await self.redis.set_json(f"signal:{symbol}:{timeframe}", result.to_dict(), ttl=86400)
                    if self.storage.enabled:
                        await self.storage.insert_signal(result)
        return snapshot, result

    def _data_fresh(self) -> bool:
        if not self.market.last_message_at:
            return self.settings.disable_auto_start
        try:
            last = datetime.fromisoformat(self.market.last_message_at)
            age = (datetime.now(timezone.utc) - last).total_seconds()
            return age <= self.settings.stale_data_seconds
        except ValueError:
            return False

    async def get_candles(self, symbol: str, timeframe: str, limit: int = 300) -> list[dict[str, Any]]:
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
        signal = self._signals.get(next((sid for sid, item in self._signals.items() if item.symbol == snapshot.symbol and item.timeframe == snapshot.timeframe), ""))
        data["result"] = signal.to_dict() if signal else {"decision": "NO TRADE", "reasons": snapshot.reasons, "score": max(snapshot.bullish_score, snapshot.bearish_score)}
        return data

    async def get_signals(self, symbol: str, timeframe: str, limit: int = 50) -> list[dict[str, Any]]:
        local = [item.to_dict() for item in self._signals.values() if item.symbol == symbol.upper() and item.timeframe == timeframe.lower()]
        if local:
            return local[-limit:][::-1]
        if self.storage.enabled:
            return await self.storage.list_signals(symbol.upper(), timeframe.lower(), limit)
        return []

    def status(self) -> dict[str, Any]:
        return {
            "status": "ok",
            "app_version": self.settings.app_version,
            "config_version": self.settings.config_version,
            "started": self.started,
            "starting": self.starting,
            "started_at": self.started_at,
            "execution_mode": "paper",
            "cycle_count": self.cycle_count,
            "signal_count": self.signal_count,
            "last_analysis_at": self.last_analysis_at,
            "last_signal_at": self.last_signal_at,
            "subscriber_count": len(self._subscribers),
            "market": self.market.status(),
            "integrations": {"supabase_configured": self.storage.enabled, "redis_configured": bool(self.redis.url), "supabase_connected": bool(self.storage.enabled and self.storage._client), "redis_connected": self.redis.enabled},
            "settings": {"symbols": self.settings.symbols, "entry_timeframe": self.settings.entry_timeframe, "analysis_timeframes": self.settings.analysis_timeframes, "stream_timeframes": self.settings.stream_timeframes, "structure_timeframe": self.settings.structure_timeframe, "htf_timeframe": self.settings.htf_timeframe, "min_signal_score": self.settings.min_signal_score},
        }
