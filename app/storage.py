from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from .config import Settings
from .models import AnalysisSnapshot, Candle, Signal, Trade

logger = logging.getLogger(__name__)


class SupabaseStore:
    def __init__(self, settings: Settings):
        self.base_url = settings.supabase_url
        self.key = settings.supabase_key
        self.enabled = bool(self.base_url and self.key)
        self._client: httpx.AsyncClient | None = None

    async def startup(self) -> None:
        if self.enabled:
            self._client = httpx.AsyncClient(timeout=10.0, headers={"apikey": self.key, "Authorization": f"Bearer {self.key}", "Accept": "application/json", "Content-Type": "application/json"})

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    async def ping(self) -> bool:
        if not self.enabled or not self._client:
            return False
        try:
            response = await self._client.get(f"{self.base_url}/rest/v1/indicator_settings?select=key&limit=1")
            return response.status_code < 500
        except httpx.HTTPError as exc:
            logger.warning("supabase_ping_failed error=%s", exc)
            return False

    async def _request(self, method: str, table: str, *, params: dict[str, Any] | None = None, payload: Any = None, prefer: str | None = None) -> Any:
        if not self.enabled or not self._client:
            return None
        headers = {"Prefer": prefer} if prefer else {}
        try:
            response = await self._client.request(method, f"{self.base_url}/rest/v1/{table}", params=params, json=payload, headers=headers)
            response.raise_for_status()
            if not response.content:
                return None
            return response.json()
        except httpx.HTTPError as exc:
            logger.warning("supabase_request_failed table=%s method=%s error=%s", table, method, exc)
            return None

    async def upsert_candle(self, candle: Candle) -> Any:
        row = {
            "symbol": candle.symbol, "timeframe": candle.timeframe, "open_time": candle.open_time,
            "close_time": candle.close_time, "open": candle.open, "high": candle.high, "low": candle.low,
            "close": candle.close, "volume": candle.volume, "is_closed": candle.is_closed,
            "source": candle.source, "received_at": candle.received_at,
        }
        return await self._request("POST", "indicator_candles", payload=row, prefer="resolution=merge-duplicates,return=minimal")

    async def upsert_analysis(self, snapshot: AnalysisSnapshot) -> Any:
        row = {"symbol": snapshot.symbol, "timeframe": snapshot.timeframe, "generated_at": snapshot.generated_at, "payload": snapshot.to_dict()}
        return await self._request("POST", "indicator_analysis_snapshots", payload=row, prefer="resolution=merge-duplicates,return=minimal")

    async def insert_signal(self, signal: Signal) -> Any:
        row = {
            "id": signal.id, "symbol": signal.symbol, "timeframe": signal.timeframe,
            "direction": signal.direction, "status": signal.status, "score": signal.score,
            "entry": signal.entry, "stop_loss": signal.stop_loss, "tp1": signal.tp1, "tp2": signal.tp2,
            "created_at": signal.created_at, "signal_version": signal.signal_version,
            "reasons": signal.reasons, "payload": signal.to_dict(),
        }
        return await self._request("POST", "indicator_signals", payload=row, prefer="resolution=ignore-duplicates,return=minimal")

    async def update_signal_status(self, signal: Signal) -> Any:
        return await self._request("PATCH", f"indicator_signals?id=eq.{signal.id}", payload={"status": signal.status, "payload": signal.to_dict()}, prefer="return=minimal")

    async def insert_trade(self, trade: Trade) -> Any:
        row = trade.to_dict()
        return await self._request("POST", "indicator_trades", payload=row, prefer="resolution=merge-duplicates,return=minimal")

    async def update_trade(self, trade: Trade) -> Any:
        return await self._request("PATCH", f"indicator_trades?id=eq.{trade.id}", payload=trade.to_dict(), prefer="return=minimal")

    async def list_trades(self, symbol: str | None = None, timeframe: str | None = None, limit: int = 100, active_only: bool = False) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"select": "*", "order": "created_at.desc", "limit": str(min(max(limit, 1), 500))}
        if symbol:
            params["symbol"] = f"eq.{symbol.upper()}"
        if timeframe:
            params["timeframe"] = f"eq.{timeframe.lower()}"
        if active_only:
            params["status"] = "in.(SIGNAL_CONFIRMED,ENTRY_PENDING,ACTIVE,TP1_HIT)"
        result = await self._request("GET", "indicator_trades", params=params)
        return result if isinstance(result, list) else []

    async def list_signals(self, symbol: str, timeframe: str, limit: int = 50) -> list[dict[str, Any]]:
        result = await self._request("GET", "indicator_signals", params={"select": "*", "symbol": f"eq.{symbol}", "timeframe": f"eq.{timeframe}", "order": "created_at.desc", "limit": str(min(max(limit, 1), 200))})
        return result if isinstance(result, list) else []

    async def upsert_runtime(self, service_status: dict[str, Any]) -> Any:
        row = {"key": "default", "updated_at": service_status.get("updated_at"), "payload": service_status}
        return await self._request("POST", "indicator_runtime_state", payload=row, prefer="resolution=merge-duplicates,return=minimal")


class RedisStore:
    def __init__(self, settings: Settings):
        self.url = settings.redis_url
        self.client: Any = None
        self.enabled = False

    async def startup(self) -> None:
        if not self.url:
            return
        try:
            from redis.asyncio import Redis
            self.client = Redis.from_url(self.url, decode_responses=True, socket_timeout=3, socket_connect_timeout=3)
            await self.client.ping()
            self.enabled = True
        except Exception as exc:
            logger.warning("redis_unavailable error=%s", exc)
            self.client = None
            self.enabled = False

    async def close(self) -> None:
        if self.client:
            await self.client.aclose()
            self.client = None
            self.enabled = False

    async def set_json(self, key: str, value: Any, ttl: int = 3600) -> bool:
        if not self.enabled or not self.client:
            return False
        try:
            await self.client.set(key, json.dumps(value, separators=(",", ":")), ex=ttl)
            return True
        except Exception as exc:
            logger.warning("redis_set_failed key=%s error=%s", key, exc)
            return False

    async def get_json(self, key: str) -> Any:
        if not self.enabled or not self.client:
            return None
        try:
            raw = await self.client.get(key)
            return json.loads(raw) if raw else None
        except Exception as exc:
            logger.warning("redis_get_failed key=%s error=%s", key, exc)
            return None

    async def delete(self, key: str) -> bool:
        if not self.enabled or not self.client:
            return False
        try:
            await self.client.delete(key)
            return True
        except Exception as exc:
            logger.warning("redis_delete_failed key=%s error=%s", key, exc)
            return False
