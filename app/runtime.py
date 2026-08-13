from __future__ import annotations

import json
import logging
from collections import deque
import queue
import re
import threading
import time
from datetime import datetime, timezone
from typing import Any, Optional

from .binance_ws import BinanceMarketData
from .config import Settings
from .models import Signal, VirtualPosition
from .storage import RedisStore, SupabaseStore
from .strategy import evaluate_signal_diagnostics
from .telegram_bot import TelegramBot
from .virtual_trading import VirtualTradingEngine

logger = logging.getLogger(__name__)


class BotRuntime:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or Settings.from_env()
        self.trader = VirtualTradingEngine(self.settings)
        self.supabase = SupabaseStore(self.settings)
        self.redis = RedisStore(self.settings)
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._started = False
        self.last_signal: Signal | None = None
        self.last_event_at: datetime | None = None
        self.last_decision: dict[str, Any] | None = None
        self.last_decision_by_symbol: dict[str, dict[str, Any]] = {}
        self.cycle_count = 0
        self.signal_count = 0
        self.rejected_signal_count = 0
        self.closed_trade_count = 0
        self._last_price_log_at: dict[str, float] = {}
        self.recent_logs: deque[dict[str, Any]] = deque(maxlen=500)
        self.last_warning: dict[str, Any] | None = None
        self.last_error_log: dict[str, Any] | None = None
        
        self._sync_queue: queue.Queue[tuple[str, Any]] = queue.Queue()
        self._sync_thread: Optional[threading.Thread] = None
        
        self._history_cache: dict[str, Any] = {
            "recent_signals": [],
            "recent_positions": [],
            "events": [],
            "persisted_state": None,
            "last_updated": 0
        }
        
        self.market = BinanceMarketData(self.settings, self._on_price, self._on_closed_candle)
        self.telegram = TelegramBot(
            self.settings,
            get_status=self.status_text,
            get_prices=self.prices_text,
            get_performance=self.performance_text,
            get_positions=self.positions_text,
            get_coins=self.coins_text,
            manage_coin=self.manage_coin,
            get_keyboard=self.telegram_keyboard,
            get_symbol_status=self.symbol_status_text,
        )

    @staticmethod
    def _normalise_symbol(symbol: str) -> str:
        return re.sub(r"[^A-Z0-9]", "", symbol.upper())

    def _record_decision(self, decision: dict[str, Any]) -> None:
        self.last_decision = decision
        symbol = decision.get("symbol")
        if symbol:
            self.last_decision_by_symbol[str(symbol)] = decision

    def _load_persisted_settings(self) -> None:
        if not self.settings.telegram_chat_id:
            return
        try:
            row = self.supabase.select_one("bot_settings", "chat_id", self.settings.telegram_chat_id)
        except Exception as exc:
            logger.warning("persisted_settings_fetch_failed error=%s", exc)
            row = None

        if not row:
            logger.info("persisted_settings_not_found using_empty_user_configuration=true")
            return
        try:
            for symbol in row.get("selected_symbols") or []:
                self.trader.add_symbol(str(symbol))
            for symbol, amount in (row.get("capital_by_symbol") or {}).items():
                self.trader.set_capital(str(symbol), float(amount))
            self.market.update_symbols(list(self.trader.selected_symbols))
            logger.info("persisted_settings_loaded symbols=%s", sorted(self.trader.selected_symbols))
        except (TypeError, ValueError) as exc:
            logger.warning("persisted_settings_invalid error=%s", exc)

    def _persist_settings(self) -> None:
        if not self.settings.telegram_chat_id:
            return
        row = {
            "chat_id": self.settings.telegram_chat_id,
            "selected_symbols": sorted(self.trader.selected_symbols),
            "capital_by_symbol": self.trader.capital_by_symbol,
            "max_concurrent_positions": self.settings.max_concurrent_positions,
            "daily_loss_limit_pct": self.settings.daily_loss_limit_pct,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        self._sync_queue.put(("upsert_settings", row))
        self.redis.set_json(f"bot:settings:{self.settings.telegram_chat_id}", row, ex=86400)

    def _persist_signal(self, signal: Signal) -> None:
        row = signal.to_dict()
        row["user_id"] = self.settings.telegram_chat_id or "local"
        self._sync_queue.put(("insert_signal", row))
        self.redis.set_json(f"bot:last-signal:{signal.symbol}", row, ex=86400)

    def _persist_open_position(self, position: VirtualPosition) -> None:
        row = position.to_dict()
        row["user_id"] = self.settings.telegram_chat_id or "local"
        self._sync_queue.put(("insert_position", row))

    def _persist_closed_position(self, position: VirtualPosition) -> None:
        row = position.to_dict()
        row["user_id"] = self.settings.telegram_chat_id or "local"
        self._sync_queue.put(("update_position", (position.id, row)))
        self._sync_queue.put(("insert_trade_event", {"user_id": row["user_id"], "position_id": position.id, "event_type": "CLOSED", "payload": row}))

    def _log_event(self, event_type: str, payload: dict[str, Any]) -> None:
        row = {"user_id": self.settings.telegram_chat_id or "local", "event_type": event_type, "payload": payload}
        self._sync_queue.put(("insert_event", row))

    @staticmethod
    def _redact_log_message(message: str) -> str:
        message = re.sub(r"(?i)(postgres(?:ql)?://)[^\s]+", r"\1[REDACTED]", message)
        message = re.sub(r"(?i)(password|secret|token|apikey|api_key|authorization)[=: ]+[^\s]+", r"\1=[REDACTED]", message)
        return message[:2000]

    def add_runtime_log(self, level: str, message: str, logger_name: str = "app", persist: bool = True) -> None:
        level = level.upper()
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": level,
            "logger": logger_name,
            "message": self._redact_log_message(message),
        }
        with self._lock:
            self.recent_logs.append(record)
            if level in ("ERROR", "CRITICAL"):
                self.last_error_log = record
            elif level == "WARNING":
                self.last_warning = record
        
        if persist and level in ("WARNING", "ERROR", "CRITICAL"):
            self._log_event("runtime_log", record)

    def health(self) -> dict[str, Any]:
        return {
            "status": "ok",
            "runtime_started": self._started,
            "websocket_connected": self.market.connected,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    def dashboard_snapshot(self) -> dict[str, Any]:
        try:
            # Minimal snapshot to isolate 500 error
            return {
                "overview": {
                    "service": "CT Binance Spot Live Recommendations",
                    "runtime_started": self._started,
                    "websocket_connected": self.market.connected,
                    "live_data_available": self.market.live_data_available,
                    "cycles": self.cycle_count,
                    "signals": self.signal_count,
                    "win_rate": 0.0,
                    "sharpe_ratio": 0.0,
                    "max_drawdown": 0.0,
                    "total_capital": 0.0,
                    "realized_pnl_today": 0.0,
                    "open_positions_count": 0,
                    "coins": []
                },
                "open_positions": [],
                "recent_signals": [],
                "recent_positions": [],
                "events": [],
                "logs": [],
                "errors": [],
                "warnings": []
            }
        except Exception as e:
            return {"error": str(e)}

    def history_snapshot(self) -> dict[str, Any]:
        return {
            "recent_signals": [],
            "recent_positions": [],
            "events": [],
            "logs": []
        }

    def _on_price(self, symbol: str, price: float) -> None:
        symbol = self._normalise_symbol(symbol)
        with self._lock:
            if symbol not in self.trader.selected_symbols:
                return
            self.last_event_at = datetime.now(timezone.utc)
            closed = self.trader.on_price(symbol, price)
            for position in closed:
                self.closed_trade_count += 1
                self._persist_closed_position(position)
                threading.Thread(target=self.telegram.alert, args=(f"Closed {position.symbol}",), daemon=True).start()

    def _on_closed_candle(self, symbol: str, interval: str, candle: dict[str, Any]) -> None:
        symbol = self._normalise_symbol(symbol)
        with self._lock:
            if interval == self.settings.execution_timeframe:
                self.cycle_count += 1

    def start(self) -> None:
        with self._lock:
            if self._started: return
            self._started = True
            self._stop.clear()
            self.market.start()
            self.telegram.start()
            self._sync_thread = threading.Thread(target=self._sync_worker, name="sync-worker", daemon=True)
            self._sync_thread.start()

    def stop(self) -> None:
        with self._lock:
            self._started = False
            self._stop.set()
            self.market.stop()
            self.telegram.stop()

    def _sync_worker(self) -> None:
        while not self._stop.is_set():
            try:
                task = self._sync_queue.get(timeout=1.0)
                self._sync_queue.task_done()
            except queue.Empty:
                continue

    def status_text(self) -> str: return "Status"
    def prices_text(self) -> str: return "Prices"
    def performance_text(self) -> str: return "Performance"
    def positions_text(self) -> str: return "Positions"
    def coins_text(self) -> str: return "Coins"
    def manage_coin(self, command: str) -> str: return "Managed"
    def telegram_keyboard(self) -> dict[str, Any]: return {"keyboard": [["Status"]]}
    def symbol_status_text(self, symbol: str) -> str: return "Symbol Status"
