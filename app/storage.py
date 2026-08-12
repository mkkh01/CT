from __future__ import annotations

import json
import logging
from typing import Any, Optional
from urllib.parse import quote

import requests

from .config import Settings

logger = logging.getLogger(__name__)


class SupabaseStore:
    def __init__(self, settings: Settings):
        self.base_url = settings.supabase_url
        self.key = settings.supabase_key
        self.session = requests.Session()
        self.enabled = bool(self.base_url and self.key)
        if settings.supabase_url_issue:
            logger.error("supabase_disabled_invalid_configuration reason=%s", settings.supabase_url_issue)

    def _request(self, method: str, table: str, **kwargs: Any) -> Optional[Any]:
        if not self.enabled:
            return None
        url = f"{self.base_url}/rest/v1/{table}"
        headers = {
            "apikey": self.key,
            "Authorization": f"Bearer {self.key}",
            "Content-Type": "application/json",
            "Prefer": "return=representation",
        }
        headers.update(kwargs.pop("headers", {}))
        try:
            response = self.session.request(method, url, headers=headers, timeout=10, **kwargs)
            response.raise_for_status()
            if not response.content:
                return None
            return response.json()
        except requests.RequestException as exc:
            logger.warning("supabase_request_failed table=%s error=%s", table, exc)
            return None

    def upsert(self, table: str, row: dict[str, Any], conflict_column: str) -> Optional[Any]:
        return self._request("POST", f"{table}?on_conflict={conflict_column}", json=row, headers={"Prefer": "resolution=merge-duplicates,return=representation"})

    def insert(self, table: str, row: dict[str, Any]) -> Optional[Any]:
        return self._request("POST", table, json=row)

    def select_one(self, table: str, column: str, value: str) -> Optional[dict[str, Any]]:
        result = self._request("GET", f"{table}?select=*&{column}=eq.{value}&limit=1")
        return result[0] if isinstance(result, list) and result else None

    def select_open_positions(self, user_id: str) -> list[dict[str, Any]]:
        result = self._request("GET", f"virtual_positions?select=*&user_id=eq.{user_id}&status=eq.OPEN&limit=20")
        return result if isinstance(result, list) else []

    def update_position(self, position_id: str, row: dict[str, Any]) -> Optional[Any]:
        return self._request("PATCH", f"virtual_positions?id=eq.{position_id}", json=row)

    def _user_filter(self, user_id: str) -> str:
        return quote(str(user_id), safe="")

    def select_recent_signals(self, user_id: str, limit: int = 100) -> list[dict[str, Any]]:
        columns = "id,symbol,timeframe,generated_at,candle_open_time,entry_price,stop_loss,take_profit,reason,risk_reward,status,created_at"
        result = self._request(
            "GET",
            f"signals?select={columns}&user_id=eq.{self._user_filter(user_id)}&order=created_at.desc&limit={min(max(limit, 1), 500)}",
        )
        return result if isinstance(result, list) else []

    def select_recent_positions(self, user_id: str, limit: int = 100) -> list[dict[str, Any]]:
        columns = "id,signal_id,symbol,capital_allocated,entry_price,stop_loss,take_profit,quantity,opened_at,status,exit_price,closed_at,realized_pnl,close_reason,created_at"
        result = self._request(
            "GET",
            f"virtual_positions?select={columns}&user_id=eq.{self._user_filter(user_id)}&order=created_at.desc&limit={min(max(limit, 1), 500)}",
        )
        return result if isinstance(result, list) else []

    def select_recent_events(self, user_id: str, limit: int = 250) -> list[dict[str, Any]]:
        columns = "id,event_type,payload,created_at"
        result = self._request(
            "GET",
            f"system_events?select={columns}&user_id=eq.{self._user_filter(user_id)}&order=created_at.desc&limit={min(max(limit, 1), 500)}",
        )
        return result if isinstance(result, list) else []


class RedisStore:
    def __init__(self, settings: Settings):
        self.client = None
        self.enabled = False
        if settings.redis_url:
            try:
                import redis

                self.client = redis.from_url(settings.redis_url, decode_responses=True, socket_timeout=3)
                self.client.ping()
                self.enabled = True
            except Exception as exc:  # redis is optional during local tests
                logger.warning("redis_unavailable error=%s", exc)

    def set_json(self, key: str, value: Any, ex: int = 3600) -> bool:
        if not self.enabled:
            return False
        try:
            self.client.set(key, json.dumps(value), ex=ex)
            return True
        except Exception as exc:
            logger.warning("redis_set_failed key=%s error=%s", key, exc)
            return False

    def get_json(self, key: str) -> Optional[Any]:
        if not self.enabled:
            return None
        try:
            value = self.client.get(key)
            return json.loads(value) if value else None
        except Exception as exc:
            logger.warning("redis_get_failed key=%s error=%s", key, exc)
            return None

    def delete(self, key: str) -> bool:
        if not self.enabled:
            return False
        try:
            self.client.delete(key)
            return True
        except Exception as exc:
            logger.warning("redis_delete_failed key=%s error=%s", key, exc)
            return False
