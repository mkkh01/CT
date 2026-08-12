from __future__ import annotations

import json
import logging
import threading
import time
from collections import defaultdict, deque
from datetime import datetime, timezone
from typing import Any, Callable, Optional

import requests
import websocket
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .config import Settings

logger = logging.getLogger(__name__)


class BinanceMarketData:
    def __init__(
        self,
        settings: Settings,
        on_price: Callable[[str, float], None],
        on_closed_candle: Callable[[str, str, dict[str, Any]], None],
    ):
        self.settings = settings
        self.on_price = on_price
        self.on_closed_candle = on_closed_candle
        self.symbols = sorted({symbol.upper() for symbol in settings.selected_symbols})
        self._candles: dict[tuple[str, str], deque[dict[str, Any]]] = defaultdict(lambda: deque(maxlen=300))
        self._bootstrap_state: dict[tuple[str, str], dict[str, Any]] = {}
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._ws: Optional[websocket.WebSocketApp] = None
        self._last_message_at: Optional[float] = None
        self._connected = False
        self._rest_session = requests.Session()
        self._rest_session.headers.update({
            "User-Agent": "CT-Spot-Monitor/1.0",
            "Accept": "application/json",
            "Connection": "close",
        })
        retry = Retry(
            total=2,
            connect=2,
            read=2,
            backoff_factor=0.35,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=frozenset({"GET"}),
            raise_on_status=False,
        )
        self._rest_session.mount("https://", HTTPAdapter(max_retries=retry))
        self._rest_urls = self._build_rest_urls()
        self._active_rest_url = self._rest_urls[0]
        self._bootstrap_rate_limited_until = 0.0
        self._last_rate_limit_log_at = 0.0
        self._prepare_bootstrap_state()

    def _build_rest_urls(self) -> list[str]:
        configured = self.settings.binance_rest_url.rstrip("/")
        urls = [configured]
        if configured == "https://api.binance.com/api/v3":
            urls.extend([f"https://api{i}.binance.com/api/v3" for i in range(1, 5)])
        return list(dict.fromkeys(urls))

    @property
    def connected(self) -> bool:
        return self._connected

    @property
    def last_message_at(self) -> Optional[float]:
        return self._last_message_at

    def _prepare_bootstrap_state(self) -> None:
        for symbol in self.symbols:
            for interval in (self.settings.execution_timeframe, self.settings.higher_timeframe):
                self._bootstrap_state.setdefault((symbol, interval), {"status": "pending", "count": 0, "last_error": None, "updated_at": None})

    def update_symbols(self, symbols: list[str]) -> None:
        self.symbols = sorted({symbol.upper() for symbol in symbols})
        self._prepare_bootstrap_state()
        logger.info("market_symbols_updated symbols=%s restart_required=true", self.symbols)

    def candles(self, symbol: str, interval: str) -> list[dict[str, Any]]:
        return [candle for candle in self._candles[(symbol.upper(), interval)] if candle.get("closed")]

    def _set_bootstrap_state(self, symbol: str, interval: str, status: str, error: str | None = None) -> None:
        self._bootstrap_state[(symbol, interval)] = {
            "status": status,
            "count": len(self.candles(symbol, interval)),
            "last_error": error,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }

    def _retry_after_seconds(self, response: requests.Response) -> int:
        raw = response.headers.get("Retry-After", "")
        try:
            value = int(float(raw))
        except (TypeError, ValueError):
            value = 60
        return max(30, min(value, 900))

    def _fetch_klines(self, symbol: str, interval: str) -> Optional[list[Any]]:
        now = time.time()
        if now < self._bootstrap_rate_limited_until:
            self._set_bootstrap_state(symbol, interval, "rate_limited_cooldown", "binance_rest_cooldown")
            return None

        last_error: str | None = None
        for base_url in [self._active_rest_url] + [url for url in self._rest_urls if url != self._active_rest_url]:
            try:
                params = {"symbol": symbol, "interval": interval, "limit": 200}
                response = self._rest_session.get(f"{base_url}/klines", params=params, timeout=15)
                if response.status_code in (418, 429):
                    cooldown = self._retry_after_seconds(response)
                    self._bootstrap_rate_limited_until = time.time() + cooldown
                    last_error = f"HTTP_{response.status_code}_rate_limit"
                    now = time.time()
                    if now - self._last_rate_limit_log_at >= 60:
                        logger.warning(
                            "market_bootstrap_rate_limited symbol=%s interval=%s status=%s endpoint=%s cooldown_seconds=%s",
                            symbol,
                            interval,
                            response.status_code,
                            base_url,
                            cooldown,
                        )
                        self._last_rate_limit_log_at = now
                    # Do not hammer the remaining endpoints after a ban response.
                    break
                if response.status_code >= 500:
                    last_error = f"HTTP_{response.status_code}"
                    continue
                response.raise_for_status()
                self._active_rest_url = base_url
                return response.json()
            except (requests.RequestException, ValueError) as exc:
                last_error = str(exc)
                continue
        if last_error:
            self._set_bootstrap_state(symbol, interval, "unavailable", last_error)
        return None

    def bootstrap(self) -> None:
        self._prepare_bootstrap_state()
        for symbol in self.symbols:
            for interval in (self.settings.execution_timeframe, self.settings.higher_timeframe):
                raw_klines = self._fetch_klines(symbol, interval)
                if raw_klines is None:
                    state = self._bootstrap_state[(symbol, interval)]
                    if state.get("status") == "rate_limited_cooldown":
                        logger.info("market_bootstrap_deferred symbol=%s interval=%s reason=binance_rest_cooldown", symbol, interval)
                    else:
                        logger.warning("market_bootstrap_failed symbol=%s interval=%s reason=%s", symbol, interval, state.get("last_error"))
                    continue
                for raw in raw_klines:
                    self._store_candle(symbol, interval, self._normalise_rest_kline(raw))
                self._set_bootstrap_state(symbol, interval, "ready")
                logger.info("market_bootstrap_complete symbol=%s interval=%s count=%s endpoint=%s", symbol, interval, len(self.candles(symbol, interval)), self._active_rest_url)

    @staticmethod
    def _normalise_rest_kline(raw: list[Any]) -> dict[str, Any]:
        close_time = int(raw[6])
        return {
            "open_time": int(raw[0]),
            "close_time": close_time,
            "open": float(raw[1]),
            "high": float(raw[2]),
            "low": float(raw[3]),
            "close": float(raw[4]),
            "volume": float(raw[5]),
            "closed": close_time <= int(time.time() * 1000),
        }

    @staticmethod
    def _normalise_stream_kline(kline: dict[str, Any]) -> dict[str, Any]:
        return {
            "open_time": int(kline["t"]),
            "close_time": int(kline["T"]),
            "open": float(kline["o"]),
            "high": float(kline["h"]),
            "low": float(kline["l"]),
            "close": float(kline["c"]),
            "volume": float(kline["v"]),
            "closed": bool(kline["x"]),
        }

    def _store_candle(self, symbol: str, interval: str, candle: dict[str, Any]) -> None:
        bucket = self._candles[(symbol.upper(), interval)]
        if bucket and bucket[-1]["open_time"] == candle["open_time"]:
            bucket[-1] = candle
        else:
            bucket.append(candle)
        if candle.get("closed"):
            state = self._bootstrap_state.setdefault((symbol.upper(), interval), {"status": "streaming", "count": 0, "last_error": None, "updated_at": None})
            if state.get("status") in ("pending", "unavailable", "rate_limited_cooldown"):
                state["status"] = "streaming_partial"
            state["count"] = len(self.candles(symbol, interval))
            state["updated_at"] = datetime.now(timezone.utc).isoformat()

    def status_snapshot(self) -> dict[str, Any]:
        self._prepare_bootstrap_state()
        by_symbol: dict[str, Any] = {}
        for symbol in self.symbols:
            intervals: dict[str, Any] = {}
            for interval in (self.settings.execution_timeframe, self.settings.higher_timeframe):
                state = dict(self._bootstrap_state.get((symbol, interval), {}))
                state["count"] = len(self.candles(symbol, interval))
                intervals[interval] = state
            required = 55
            ready = all(item.get("count", 0) >= required for item in intervals.values())
            by_symbol[symbol] = {
                "price": None,
                "intervals": intervals,
                "required_closed_candles": required,
                "ready_for_strategy": ready,
                "readiness_reason": "ready" if ready else "waiting_for_55_closed_candles_on_1h_and_4h",
            }
        return {
            "connected": self.connected,
            "last_message_at": datetime.fromtimestamp(self._last_message_at, timezone.utc).isoformat() if self._last_message_at else None,
            "active_rest_url": self._active_rest_url,
            "rest_cooldown_until": datetime.fromtimestamp(self._bootstrap_rate_limited_until, timezone.utc).isoformat() if self._bootstrap_rate_limited_until > time.time() else None,
            "symbols": by_symbol,
            "strategy_ready_symbols": sorted(symbol for symbol, state in by_symbol.items() if state["ready_for_strategy"]),
        }

    def _handle_message(self, raw_message: str) -> None:
        message = json.loads(raw_message)
        data = message.get("data", message)
        event_type = data.get("e")
        self._last_message_at = time.time()
        if event_type == "24hrMiniTicker":
            symbol = str(data["s"]).upper()
            self.on_price(symbol, float(data["c"]))
            return
        if event_type == "kline":
            kline = data["k"]
            symbol = str(data["s"]).upper()
            interval = str(kline["i"])
            candle = self._normalise_stream_kline(kline)
            self._store_candle(symbol, interval, candle)
            if candle["closed"]:
                self.on_closed_candle(symbol, interval, candle)

    def _build_url(self) -> str:
        streams = []
        for symbol in self.symbols:
            lower = symbol.lower()
            streams.extend([f"{lower}@kline_{self.settings.execution_timeframe}", f"{lower}@kline_{self.settings.higher_timeframe}", f"{lower}@miniTicker"])
        return f"{self.settings.binance_stream_url}?streams={'/'.join(streams)}"

    def _run(self) -> None:
        backoff = 2
        while not self._stop.is_set():
            if not self.symbols:
                self._stop.wait(5)
                continue
            url = self._build_url()
            logger.info("binance_ws_connecting streams=%s", url.split("?streams=")[-1])

            def on_open(_ws: websocket.WebSocketApp) -> None:
                nonlocal backoff
                self._connected = True
                backoff = 2
                logger.info("binance_ws_connected")

            def on_message(_ws: websocket.WebSocketApp, message: str) -> None:
                try:
                    self._handle_message(message)
                except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
                    logger.warning("binance_ws_message_invalid error=%s", exc)

            def on_error(_ws: websocket.WebSocketApp, error: Any) -> None:
                logger.warning("binance_ws_error error=%s", error)

            def on_close(_ws: websocket.WebSocketApp, code: Any, reason: Any) -> None:
                self._connected = False
                logger.warning("binance_ws_closed code=%s reason=%s", code, reason)

            def on_ping(ws: websocket.WebSocketApp, message: str) -> None:
                try:
                    ws.sock.pong(message)
                except Exception:
                    pass

            self._ws = websocket.WebSocketApp(url, on_open=on_open, on_message=on_message, on_error=on_error, on_close=on_close, on_ping=on_ping)
            try:
                self._ws.run_forever(ping_interval=15, ping_timeout=10, ping_payload="")
            except Exception as exc:
                logger.warning("binance_ws_run_failed error=%s", exc)
            finally:
                self._connected = False
            wait_seconds = min(backoff, 30)
            backoff = min(backoff * 2, 30)
            if not self._stop.wait(wait_seconds):
                logger.info("binance_ws_reconnect_wait_seconds=%s", wait_seconds)

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self.bootstrap()
        self._thread = threading.Thread(target=self._run, name="binance-ws", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._ws:
            try:
                self._ws.close()
            except Exception:
                pass
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)

    def restart(self) -> None:
        """Reconnect with the current symbol list after a Telegram settings change."""
        self.stop()
        self.start()
