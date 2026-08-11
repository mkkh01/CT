from __future__ import annotations

import json
import logging
import threading
import time
from collections import defaultdict, deque
from typing import Any, Callable, Optional

import requests
import websocket

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
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._ws: Optional[websocket.WebSocketApp] = None
        self._last_message_at: Optional[float] = None
        self._connected = False

    @property
    def connected(self) -> bool:
        return self._connected

    @property
    def last_message_at(self) -> Optional[float]:
        return self._last_message_at

    def update_symbols(self, symbols: list[str]) -> None:
        self.symbols = sorted({symbol.upper() for symbol in symbols})
        logger.info("market_symbols_updated symbols=%s restart_required=true", self.symbols)

    def candles(self, symbol: str, interval: str) -> list[dict[str, Any]]:
        return list(self._candles[(symbol.upper(), interval)])

    def bootstrap(self) -> None:
        for symbol in self.symbols:
            for interval in (self.settings.execution_timeframe, self.settings.higher_timeframe):
                try:
                    params = {"symbol": symbol, "interval": interval, "limit": 200}
                    response = requests.get(f"{self.settings.binance_rest_url}/klines", params=params, timeout=15)
                    response.raise_for_status()
                    for raw in response.json():
                        self._store_candle(symbol, interval, self._normalise_rest_kline(raw))
                    logger.info("market_bootstrap_complete symbol=%s interval=%s count=%s", symbol, interval, len(self.candles(symbol, interval)))
                except requests.RequestException as exc:
                    logger.warning("market_bootstrap_failed symbol=%s interval=%s error=%s", symbol, interval, exc)

    @staticmethod
    def _normalise_rest_kline(raw: list[Any]) -> dict[str, Any]:
        return {
            "open_time": int(raw[0]),
            "close_time": int(raw[6]),
            "open": float(raw[1]),
            "high": float(raw[2]),
            "low": float(raw[3]),
            "close": float(raw[4]),
            "volume": float(raw[5]),
            "closed": True,
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
                time.sleep(5)
                continue
            url = self._build_url()
            logger.info("binance_ws_connecting streams=%s", url.split("?streams=")[-1])

            def on_open(_ws: websocket.WebSocketApp) -> None:
                self._connected = True
                backoff_nonlocal[0] = 2
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

            backoff_nonlocal = [backoff]
            self._ws = websocket.WebSocketApp(
                url,
                on_open=on_open,
                on_message=on_message,
                on_error=on_error,
                on_close=on_close,
                on_ping=on_ping,
            )
            try:
                self._ws.run_forever(ping_interval=15, ping_timeout=10, ping_payload="")
            except Exception as exc:
                logger.warning("binance_ws_run_failed error=%s", exc)
            finally:
                self._connected = False
            backoff = min(backoff_nonlocal[0] * 2, 30)
            if not self._stop.wait(backoff_nonlocal[0]):
                logger.info("binance_ws_reconnect_wait_seconds=%s", backoff_nonlocal[0])

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
