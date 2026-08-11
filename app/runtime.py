from __future__ import annotations

import json
import logging
import threading
import time
from datetime import datetime, timezone
from typing import Any

from .binance_ws import BinanceMarketData
from .config import Settings
from .models import Signal, VirtualPosition
from .storage import RedisStore, SupabaseStore
from .strategy import evaluate_signal
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
        self._summary_thread: threading.Thread | None = None
        self._started = False
        self.last_signal: Signal | None = None
        self.last_error: str | None = None
        self.last_event_at: datetime | None = None
        self.market = BinanceMarketData(self.settings, self._on_price, self._on_closed_candle)
        self.telegram = TelegramBot(
            self.settings,
            get_status=self.status_text,
            get_prices=self.prices_text,
            get_performance=self.performance_text,
            get_positions=self.positions_text,
            set_capital=self.set_capital,
            manage_symbol=self.manage_symbol,
        )

    def _load_persisted_settings(self) -> None:
        if not self.settings.telegram_chat_id:
            return
        row = self.supabase.select_one("bot_settings", "chat_id", self.settings.telegram_chat_id)
        if not row:
            return
        try:
            for symbol in row.get("selected_symbols") or []:
                self.trader.add_symbol(str(symbol))
            for symbol, amount in (row.get("capital_by_symbol") or {}).items():
                self.trader.set_capital(str(symbol), float(amount))
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
        self.supabase.upsert("bot_settings", row, "chat_id")
        self.redis.set_json(f"bot:settings:{self.settings.telegram_chat_id}", row, ex=86400)

    def _persist_signal(self, signal: Signal) -> None:
        row = signal.to_dict()
        row["user_id"] = self.settings.telegram_chat_id or "local"
        self.supabase.insert("signals", row)
        self.redis.set_json(f"bot:last-signal:{signal.symbol}", row, ex=86400)

    def _persist_open_position(self, position: VirtualPosition) -> None:
        row = position.to_dict()
        row["user_id"] = self.settings.telegram_chat_id or "local"
        self.supabase.insert("virtual_positions", row)

    def _persist_closed_position(self, position: VirtualPosition) -> None:
        row = position.to_dict()
        row["user_id"] = self.settings.telegram_chat_id or "local"
        self.supabase.update_position(position.id, row)
        self.supabase.insert("trade_events", {"user_id": row["user_id"], "position_id": position.id, "event_type": "CLOSED", "payload": row})

    def _log_event(self, event_type: str, payload: dict[str, Any]) -> None:
        row = {"user_id": self.settings.telegram_chat_id or "local", "event_type": event_type, "payload": payload}
        self.supabase.insert("system_events", row)

    def _on_price(self, symbol: str, price: float) -> None:
        with self._lock:
            self.last_event_at = datetime.now(timezone.utc)
            closed = self.trader.on_price(symbol, price)
            for position in closed:
                self._persist_closed_position(position)
                self.telegram.alert(
                    f"انتهت الصفقة الافتراضية {position.symbol}\n"
                    f"السبب: {position.close_reason}\n"
                    f"الدخول: {position.entry_price:.8f}\n"
                    f"الخروج: {position.exit_price:.8f}\n"
                    f"النتيجة الافتراضية: {position.realized_pnl:.8f} USDT\n"
                    f"أداء اليوم: {self.trader.realized_pnl_today:.8f} USDT"
                )
                self._log_event("virtual_position_closed", position.to_dict())

    def _on_closed_candle(self, symbol: str, interval: str, _candle: dict[str, Any]) -> None:
        if interval != self.settings.execution_timeframe:
            return
        with self._lock:
            self.last_event_at = datetime.now(timezone.utc)
            execution = self.market.candles(symbol, self.settings.execution_timeframe)
            higher = self.market.candles(symbol, self.settings.higher_timeframe)
            signal = evaluate_signal(
                symbol,
                execution,
                higher,
                stop_loss_pct=self.settings.stop_loss_pct,
                take_profit_r_multiple=self.settings.take_profit_r_multiple,
            )
            if signal is None:
                logger.info("summary_cycle signal=none symbol=%s interval=%s", symbol, interval)
                return
            if self.trader.last_signal_at.get(symbol) == signal.candle_open_time:
                return
            self.last_signal = signal
            self._persist_signal(signal)
            position, status = self.trader.open_from_signal(signal)
            if position:
                self._persist_open_position(position)
                text = (
                    f"توصية شراء Spot — {signal.symbol}\n"
                    f"الإطار: {signal.timeframe} | نوع التنبيه: افتراضي\n"
                    f"الدخول المرجعي: {signal.entry_price:.8f}\n"
                    f"وقف الخسارة: {signal.stop_loss:.8f}\n"
                    f"الهدف: {signal.take_profit:.8f}\n"
                    f"Risk/Reward: {signal.risk_reward:.2f}R\n"
                    f"السبب: {signal.reason}\n\n"
                    "تم فتح متابعة افتراضية فقط؛ لم يُرسل أي أمر إلى Binance."
                )
                self.telegram.alert(text)
                self._log_event("virtual_position_opened", position.to_dict())
            else:
                self.telegram.alert(
                    f"إشارة {signal.symbol} موجودة، لكن لم تُفتح متابعة افتراضية.\nالسبب: {status}"
                )

    def set_capital(self, symbol: str, amount: float) -> str:
        with self._lock:
            try:
                self.trader.set_capital(symbol, amount)
                self._persist_settings()
                return f"تم ضبط رأس مال {symbol.upper()} على {amount:.8f} USDT. سيُستخدم كامل المبلغ في المتابعة الافتراضية لهذه العملة."
            except ValueError as exc:
                return f"تعذر ضبط رأس المال: {exc}"

    def manage_symbol(self, command: str) -> str:
        action, symbol = command.split(":", 1)
        symbol = symbol.upper()
        with self._lock:
            if action == "add":
                self.trader.add_symbol(symbol)
                self.market.update_symbols(sorted(self.trader.selected_symbols))
                self._persist_settings()
                if self._started:
                    self.market.restart()
                return f"تمت إضافة {symbol}. أضف رأس مالها عبر زر إضافة رأس مال."
            if action == "remove":
                if not self.trader.remove_symbol(symbol):
                    return f"لا يمكن حذف {symbol} أثناء وجود صفقة افتراضية مفتوحة."
                self.market.update_symbols(sorted(self.trader.selected_symbols))
                self._persist_settings()
                if self._started:
                    self.market.restart()
                return f"تم حذف {symbol} من قائمة المتابعة."
            return "أمر العملات غير معروف."

    def prices_text(self) -> str:
        snapshot = self.trader.snapshot()
        if not snapshot["last_prices"]:
            return "لا توجد أسعار مستلمة بعد من Binance WebSocket."
        lines = ["الأسعار الحية من Binance WebSocket:"]
        for symbol in sorted(snapshot["last_prices"]):
            lines.append(f"{symbol}: {snapshot['last_prices'][symbol]:.8f}")
        return "\n".join(lines)

    def performance_text(self) -> str:
        snapshot = self.trader.snapshot()
        total = snapshot["total_capital"]
        pnl = snapshot["realized_pnl_today"]
        pct = (pnl / total * 100) if total else 0.0
        return (
            "أداء النظام الافتراضي اليوم\n"
            f"رأس المال المعرّف: {total:.8f} USDT\n"
            f"النتيجة المحققة افتراضياً: {pnl:.8f} USDT ({pct:.2f}%)\n"
            f"حد الخسارة اليومية: {snapshot['daily_loss_limit_amount']:.8f} USDT ({self.settings.daily_loss_limit_pct * 100:.2f}%)\n"
            f"حالة الحد اليومي: {'متوقف' if snapshot['daily_loss_limit_hit'] else 'نشط'}"
        )

    def positions_text(self) -> str:
        positions = list(self.trader.positions.values())
        if not positions:
            return "لا توجد صفقات افتراضية مفتوحة."
        lines = ["الصفقات الافتراضية المفتوحة:"]
        for position in positions:
            current = self.trader.last_prices.get(position.symbol, position.entry_price)
            pnl = (current - position.entry_price) * position.quantity
            lines.append(
                f"{position.symbol} | دخول {position.entry_price:.8f} | الآن {current:.8f} | "
                f"وقف {position.stop_loss:.8f} | هدف {position.take_profit:.8f} | PnL {pnl:.8f} USDT"
            )
        return "\n".join(lines)

    def status_text(self) -> str:
        snapshot = self.trader.snapshot()
        ws = "متصل" if self.market.connected else "غير متصل"
        last_event = self.last_event_at.isoformat() if self.last_event_at else "لا يوجد"
        missing = ", ".join(self.settings.missing_integrations()) or "لا يوجد"
        return (
            "حالة النظام\n"
            f"Binance WebSocket: {ws}\n"
            f"آخر حدث: {last_event}\n"
            f"العملات: {', '.join(snapshot['selected_symbols']) or 'غير محددة'}\n"
            f"الصفقات المفتوحة: {len(snapshot['open_positions'])}/{self.settings.max_concurrent_positions}\n"
            f"Supabase/Redis الناقص: {missing}\n"
            "التنفيذ: توصيات ومتابعة افتراضية فقط، بلا أوامر Binance"
        )

    def _summary_loop(self) -> None:
        while not self._stop.wait(60):
            with self._lock:
                snapshot = self.trader.snapshot()
                snapshot["websocket_connected"] = self.market.connected
                snapshot["last_event_at"] = self.last_event_at.isoformat() if self.last_event_at else None
                logger.info("summary_cycle %s", json.dumps(snapshot, ensure_ascii=False, default=str))
                self.redis.set_json("bot:summary", snapshot, ex=300)
                self._log_event("summary_cycle", snapshot)

    def start(self) -> None:
        if self._started:
            return
        self._load_persisted_settings()
        self.market.update_symbols(sorted(self.trader.selected_symbols))
        self.market.start()
        self.telegram.start()
        self._stop.clear()
        self._summary_thread = threading.Thread(target=self._summary_loop, name="summary-cycle", daemon=True)
        self._summary_thread.start()
        self._started = True
        logger.info("runtime_started symbols=%s", sorted(self.trader.selected_symbols))

    def stop(self) -> None:
        self._stop.set()
        self.telegram.stop()
        self.market.stop()
        if self._summary_thread and self._summary_thread.is_alive():
            self._summary_thread.join(timeout=5)
        self._started = False

    def health(self) -> dict[str, Any]:
        return {
            "status": "ok",
            "runtime_started": self._started,
            "websocket_connected": self.market.connected,
            "last_event_at": self.last_event_at.isoformat() if self.last_event_at else None,
            "open_positions": len(self.trader.positions),
            "selected_symbols": sorted(self.trader.selected_symbols),
            "missing_integrations": self.settings.missing_integrations(),
        }
