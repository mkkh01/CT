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

    def health(self) -> dict[str, Any]:
        return {
            "status": "ok",
            "runtime_started": self._started,
            "websocket_connected": self.market.connected,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    def dashboard_snapshot(self) -> dict[str, Any]:
        try:
            symbols = sorted(list(self.trader.selected_symbols))
            market_status = self.market.status_snapshot()
            
            overview = {
                "service": "CT Binance Spot Live Recommendations",
                "runtime_started": self._started,
                "websocket_connected": self.market.connected,
                "live_data_available": self.market.live_data_available,
                "last_event_at": self.last_event_at.isoformat() if self.last_event_at else None,
                "coins": [{"symbol": s} for s in symbols],
                "total_capital": self.trader.total_capital(),
                "realized_pnl_today": self.trader.realized_pnl_today,
                "open_positions_count": len(self.trader.positions),
                "cycles": self.cycle_count,
                "signals": self.signal_count,
                "win_rate": 0.0,
                "sharpe_ratio": 0.0,
                "max_drawdown": 0.0,
                "market_status": market_status
            }
            
            return {
                "overview": overview,
                "open_positions": [],
                "recent_signals": [],
                "recent_positions": [],
                "events": [],
                "logs": list(self.recent_logs)[-50:]
            }
        except Exception as e:
            logger.error(f"dashboard_snapshot_error: {e}")
            return {"error": str(e)}

    def history_snapshot(self) -> dict[str, Any]:
        return {
            "recent_signals": self._history_cache.get("recent_signals", []),
            "recent_positions": self._history_cache.get("recent_positions", []),
            "events": self._history_cache.get("events", []),
            "logs": list(self.recent_logs)[-100:][::-1],
        }

    def _on_price(self, symbol: str, price: float) -> None:
        pass

    def _on_closed_candle(self, symbol: str, interval: str, candle: dict[str, Any]) -> None:
        pass

    def _load_persisted_settings(self) -> None:
        pass

    def _persist_settings(self) -> None:
        pass

    def _sync_worker(self) -> None:
        while not self._stop.is_set():
            time.sleep(1)

    def start(self) -> None:
        self._started = True
        self.market.start()
        self.telegram.start()
        self._sync_thread = threading.Thread(target=self._sync_worker, name="sync-worker", daemon=True)
        self._sync_thread.start()

    def stop(self) -> None:
        self._started = False
        self._stop.set()
        self.market.stop()
        self.telegram.stop()

    def status_text(self) -> str:
        return "System Status"

    def prices_text(self) -> str:
        return "Prices"

    def performance_text(self) -> str:
        return "Performance"

    def positions_text(self) -> str:
        return "Positions"

    def coins_text(self) -> str:
        return "Coins"

    def manage_coin(self, command: str) -> str:
        return "Manage Coin"

    def telegram_keyboard(self) -> dict[str, Any]:
        return {"keyboard": [["Status"]]}

    def symbol_status_text(self, symbol: str) -> str:
        return f"Status of {symbol}"
