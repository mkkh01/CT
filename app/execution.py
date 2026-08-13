from __future__ import annotations

import hashlib
import hmac
import logging
import time
import uuid
from dataclasses import dataclass, asdict
from typing import Any, Optional
from urllib.parse import urlencode

import requests

from .config import Settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class OrderIntent:
    client_order_id: str
    symbol: str
    side: str
    quantity: str
    order_type: str = "MARKET"
    price: Optional[str] = None
    stop_price: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ExecutionError(RuntimeError):
    pass


class ExecutionAdapter:
    mode = "paper"

    def health(self) -> dict[str, Any]:
        return {"mode": self.mode, "ready": True, "reason": "paper_mode"}

    def place_order(self, intent: OrderIntent) -> dict[str, Any]:
        raise NotImplementedError

    def get_order(self, symbol: str, client_order_id: str) -> dict[str, Any]:
        raise NotImplementedError

    def reconcile(self) -> dict[str, Any]:
        return {"reconciled": True, "mode": self.mode}


class PaperExecutionAdapter(ExecutionAdapter):
    mode = "paper"

    def place_order(self, intent: OrderIntent) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "status": "FILLED",
            "client_order_id": intent.client_order_id,
            "exchange_order_id": f"paper-{uuid.uuid4()}",
            "executed_qty": intent.quantity,
            "avg_price": intent.price,
        }

    def get_order(self, symbol: str, client_order_id: str) -> dict[str, Any]:
        return {"mode": self.mode, "status": "FILLED", "symbol": symbol, "client_order_id": client_order_id}


class BinanceSignedAdapter(ExecutionAdapter):
    """Signed Binance Spot adapter. It is never selected for live mode by default."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.mode = settings.execution_mode
        if self.mode == "testnet":
            self.base_url = "https://testnet.binance.vision/api/v3"
        else:
            self.base_url = settings.binance_rest_url or "https://api.binance.com/api/v3"
        self.api_key = settings.binance_api_key
        self.api_secret = settings.binance_api_secret
        self.session = requests.Session()
        self.time_offset_ms = 0

    def health(self) -> dict[str, Any]:
        ready, reason = self.settings.live_execution_ready()
        if not ready:
            return {"mode": self.mode, "ready": False, "reason": reason}
        try:
            response = self.session.get(f"{self.base_url}/ping", timeout=5)
            response.raise_for_status()
            return {"mode": self.mode, "ready": True, "reason": "exchange_reachable"}
        except requests.RequestException as exc:
            return {"mode": self.mode, "ready": False, "reason": f"exchange_unreachable:{exc.__class__.__name__}"}

    def _signed_request(self, method: str, path: str, params: dict[str, Any]) -> dict[str, Any]:
        ready, reason = self.settings.live_execution_ready()
        if not ready:
            raise ExecutionError(reason)
        params = {key: value for key, value in params.items() if value is not None}
        params["timestamp"] = int(time.time() * 1000) + self.time_offset_ms
        params.setdefault("recvWindow", 5000)
        query = urlencode(params)
        signature = hmac.new(self.api_secret.encode(), query.encode(), hashlib.sha256).hexdigest()
        headers = {"X-MBX-APIKEY": self.api_key}
        url = f"{self.base_url}{path}?{query}&signature={signature}"
        response = self.session.request(method, url, headers=headers, timeout=10)
        if response.status_code >= 500:
            raise ExecutionError("exchange_5xx_execution_status_unknown")
        if response.status_code in {418, 429}:
            raise ExecutionError(f"exchange_rate_limited_{response.status_code}")
        response.raise_for_status()
        payload = response.json()
        if isinstance(payload, dict) and payload.get("code", 0) < 0:
            raise ExecutionError(str(payload))
        return payload

    def place_order(self, intent: OrderIntent) -> dict[str, Any]:
        params = {
            "symbol": intent.symbol,
            "side": intent.side,
            "type": intent.order_type,
            "quantity": intent.quantity,
            "price": intent.price,
            "stopPrice": intent.stop_price,
            "newClientOrderId": intent.client_order_id,
            "newOrderRespType": "FULL",
        }
        return self._signed_request("POST", "/order", params)

    def get_order(self, symbol: str, client_order_id: str) -> dict[str, Any]:
        return self._signed_request("GET", "/order", {"symbol": symbol, "origClientOrderId": client_order_id})

    def reconcile(self) -> dict[str, Any]:
        account = self._signed_request("GET", "/account", {})
        return {"reconciled": True, "mode": self.mode, "account": account}


def build_execution_adapter(settings: Settings) -> ExecutionAdapter:
    if settings.execution_mode == "paper":
        return PaperExecutionAdapter()
    return BinanceSignedAdapter(settings)
