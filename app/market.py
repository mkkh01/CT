from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Awaitable, Callable

import httpx

from .config import Settings
from .models import Candle

logger = logging.getLogger(__name__)
CandleCallback = Callable[[Candle], Awaitable[None]]
CandleClosedCallback = Callable[[Candle], Awaitable[None]]


class CandleStore:
    def __init__(self, limit: int = 500):
        self.limit = limit
        self._data: dict[str, dict[str, list[Candle]]] = {}
        self._lock = asyncio.Lock()

    async def replace(self, candles: list[Candle]) -> None:
        if not candles:
            return
        async with self._lock:
            symbol, timeframe = candles[0].symbol, candles[0].timeframe
            self._data.setdefault(symbol, {})[timeframe] = sorted(candles, key=lambda item: item.open_time)[-self.limit:]

    async def upsert(self, candle: Candle) -> None:
        candle.validate()
        async with self._lock:
            series = self._data.setdefault(candle.symbol, {}).setdefault(candle.timeframe, [])
            for index, existing in enumerate(series):
                if existing.open_time == candle.open_time:
                    series[index] = candle
                    break
            else:
                series.append(candle)
            series.sort(key=lambda item: item.open_time)
            del series[:-self.limit]

    async def snapshot(self, symbol: str, timeframe: str) -> list[Candle]:
        async with self._lock:
            return list(self._data.get(symbol, {}).get(timeframe, []))

    async def symbols(self) -> list[str]:
        async with self._lock:
            return sorted(self._data)

    async def count(self, symbol: str, timeframe: str) -> int:
        async with self._lock:
            return len(self._data.get(symbol, {}).get(timeframe, []))


class BinanceMarketData:
    def __init__(self, settings: Settings, on_candle: CandleCallback | None = None, on_candle_closed: CandleClosedCallback | None = None):
        self.settings = settings
        self.store = CandleStore(settings.history_limit)
        self.on_candle = on_candle
        self.on_candle_closed = on_candle_closed
        self.started = False
        self.connected = False
        self.last_message_at: str | None = None
        self.last_error: str | None = None
        self._ws_task: asyncio.Task | None = None
        self._stop = asyncio.Event()
        self._client: httpx.AsyncClient | None = None

    async def start(self) -> None:
        if self.started:
            return
        self.started = True
        self._stop.clear()
        self._client = httpx.AsyncClient(timeout=15.0)
        await self.bootstrap()
        self._ws_task = asyncio.create_task(self._websocket_loop(), name="binance-market-stream")

    async def stop(self) -> None:
        self._stop.set()
        self.started = False
        self.connected = False
        if self._ws_task:
            self._ws_task.cancel()
            try:
                await self._ws_task
            except asyncio.CancelledError:
                pass
            self._ws_task = None
        if self._client:
            await self._client.aclose()
            self._client = None

    async def bootstrap(self) -> None:
        if not self._client:
            return
        sem = asyncio.Semaphore(5)

        async def load(symbol: str, timeframe: str) -> None:
            async with sem:
                try:
                    response = await self._client.get(f"{self.settings.binance_rest_url}/klines", params={"symbol": symbol, "interval": timeframe, "limit": self.settings.history_limit})
                    response.raise_for_status()
                    candles = [self._from_rest(symbol, timeframe, row) for row in response.json()]
                    for candle in candles:
                        candle.validate()
                    await self.store.replace(candles)
                except (httpx.HTTPError, ValueError, TypeError, IndexError) as exc:
                    logger.warning("bootstrap_failed symbol=%s timeframe=%s error=%s", symbol, timeframe, exc)
                    self.last_error = f"bootstrap:{symbol}:{timeframe}"

        jobs = [load(symbol, timeframe) for symbol in self.settings.symbols for timeframe in self.settings.stream_timeframes]
        await asyncio.gather(*jobs)

    async def ensure_history(self, symbol: str, timeframe: str) -> None:
        symbol, timeframe = symbol.upper(), timeframe.lower()
        if await self.store.count(symbol, timeframe) >= max(50, self.settings.atr_period + self.settings.swing_left + self.settings.swing_right + 5):
            return
        if not self._client:
            return
        try:
            response = await self._client.get(f"{self.settings.binance_rest_url}/klines", params={"symbol": symbol, "interval": timeframe, "limit": self.settings.history_limit})
            response.raise_for_status()
            candles = [self._from_rest(symbol, timeframe, row) for row in response.json()]
            for candle in candles:
                candle.validate()
            await self.store.replace(candles)
        except (httpx.HTTPError, ValueError, TypeError, IndexError) as exc:
            logger.warning("on_demand_history_failed symbol=%s timeframe=%s error=%s", symbol, timeframe, exc)
            self.last_error = f"on_demand:{symbol}:{timeframe}"

    @staticmethod
    def _from_rest(symbol: str, timeframe: str, row: list) -> Candle:
        return Candle(
            symbol=symbol, timeframe=timeframe, open_time=int(row[0]), close_time=int(row[6]),
            open=float(row[1]), high=float(row[2]), low=float(row[3]), close=float(row[4]),
            volume=float(row[5]), is_closed=(datetime.now(timezone.utc).timestamp() * 1000 >= int(row[6])), source="binance_rest",
        )

    @staticmethod
    def _from_ws(payload: dict) -> Candle | None:
        data = payload.get("data", payload)
        kline = data.get("k") if isinstance(data, dict) else None
        if not kline:
            return None
        return Candle(
            symbol=str(kline["s"]).upper(), timeframe=str(kline["i"]).lower(), open_time=int(kline["t"]), close_time=int(kline["T"]),
            open=float(kline["o"]), high=float(kline["h"]), low=float(kline["l"]), close=float(kline["c"]),
            volume=float(kline["v"]), is_closed=bool(kline["x"]), source="binance_ws",
        )

    def _stream_url(self) -> str:
        streams = "/".join(f"{symbol.lower()}@kline_{timeframe}" for symbol in self.settings.symbols for timeframe in self.settings.stream_timeframes)
        return f"{self.settings.binance_ws_url}?streams={streams}"

    async def _websocket_loop(self) -> None:
        backoff = 1
        while not self._stop.is_set():
            try:
                import websockets
                async with websockets.connect(self._stream_url(), ping_interval=20, ping_timeout=20, close_timeout=5, max_size=2**20) as websocket:
                    self.connected = True
                    self.last_error = None
                    backoff = 1
                    async for raw in websocket:
                        if self._stop.is_set():
                            break
                        self.last_message_at = datetime.now(timezone.utc).isoformat()
                        payload = json.loads(raw)
                        candle = self._from_ws(payload)
                        if candle is None:
                            continue
                        try:
                            await self.store.upsert(candle)
                        except ValueError as exc:
                            self.last_error = f"invalid_candle:{exc}"
                            continue
                        if self.on_candle:
                            await self.on_candle(candle)
                        if candle.is_closed and self.on_candle_closed:
                            await self.on_candle_closed(candle)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.connected = False
                self.last_error = type(exc).__name__
                logger.warning("binance_stream_disconnected error=%s backoff=%s", exc, backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60)
        self.connected = False

    async def snapshot(self, symbol: str, timeframe: str) -> list[Candle]:
        return await self.store.snapshot(symbol, timeframe)

    def status(self) -> dict:
        return {
            "started": self.started,
            "connected": self.connected,
            "last_message_at": self.last_message_at,
            "last_error": self.last_error,
            "symbols": self.settings.symbols,
        }
