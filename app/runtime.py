from __future__ import annotations

import json
import logging
from collections import deque
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
        self._summary_thread: threading.Thread | None = None
        self._started = False
        self.last_signal: Signal | None = None
        self.last_error: str | None = None
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
        self._persisting_runtime_log = False
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
        row = self.supabase.select_one("bot_settings", "chat_id", self.settings.telegram_chat_id)
        if not row:
            logger.info("persisted_settings_not_found using_empty_user_configuration=true")
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
            if persist and level in ("WARNING", "ERROR", "CRITICAL") and not self._persisting_runtime_log:
                self._persisting_runtime_log = True
                try:
                    self._log_event("runtime_log", record)
                finally:
                    self._persisting_runtime_log = False

    def dashboard_snapshot(self) -> dict[str, Any]:
        """Returns lightweight overview for fast UI loading."""
        with self._lock:
            trader_snapshot = self.trader.status_snapshot()
            symbols = sorted(self.trader.selected_symbols)
            coins = []
            market_status = self.market.status_snapshot()
            for symbol in symbols:
                price = market_status["symbols"].get(symbol, {}).get("price")
                decision = self.last_decision_by_symbol.get(symbol, {})
                metrics = decision.get("indicator_metrics", {})
                coin = {
                    "symbol": symbol,
                    "capital_usdt": self.trader.capital_by_symbol.get(symbol, 0.0),
                    "price": price,
                    "position_open": bool(self.trader.position_for_symbol(symbol)),
                    "market": market_status["symbols"].get(symbol),
                }
                if decision:
                    coin["analysis"] = {
                        "chart_regime_1h_label": decision.get("chart_regime_1h_label"),
                        "chart_regime_4h_label": decision.get("chart_regime_4h_label"),
                        "candle_pattern_1h": decision.get("candle_pattern_1h"),
                        "candle_pattern_4h": decision.get("candle_pattern_4h"),
                        "candle_direction_1h": decision.get("candle_direction_1h"),
                        "candle_direction_4h": decision.get("candle_direction_4h"),
                        "rejection_reason": decision.get("rejection_reason"),
                        "rejection_detail": decision.get("rejection_detail"),
                        "adx": metrics.get("adx"),
                        "atr_pct": metrics.get("atr_pct"),
                    }
                else:
                    coin["analysis"] = None
                coins.append(coin)
            overview = {
                "service": "CT Binance Spot Live Recommendations",
                "execution": "disabled",
                "runtime_started": self._started,
                "websocket_connected": self.market.connected,
                "live_data_available": self.market.live_data_available,
                "live_data_source": self.market.live_data_source,
                "last_event_at": self.last_event_at.isoformat() if self.last_event_at else None,
                "strategy": "ema_breakout_4h_filter_v1",
                "timeframes": {
                    "trigger": self.settings.trigger_timeframe,
                    "execution": self.settings.execution_timeframe,
                    "higher": self.settings.higher_timeframe
                },
                "coins": coins,
                "capital_by_symbol": self.trader.capital_by_symbol,
                "total_capital": trader_snapshot["total_capital"],
                "realized_pnl_today": trader_snapshot["realized_pnl_today"],
                "daily_loss_limit_pct": trader_snapshot["daily_loss_limit_pct"],
                "daily_loss_limit_amount": trader_snapshot["daily_loss_limit_amount"],
                "daily_loss_limit_hit": trader_snapshot["daily_loss_limit_hit"],
                "open_positions_count": len(trader_snapshot["open_positions"]),
                "max_concurrent_positions": self.settings.max_concurrent_positions,
                "cycles": self.cycle_count,
                "signals": self.signal_count,
                "rejected_signals": self.rejected_signal_count,
                "closed_trades": self.closed_trade_count,
                "last_decision": self.last_decision,
                "last_decision_by_symbol": self.last_decision_by_symbol,
                "last_signal": self.last_signal.to_dict() if self.last_signal else None,
                "missing_integrations": self.settings.missing_integrations(),
                "market_status": market_status,
                "strategy_ready": bool(market_status["strategy_ready_symbols"]) and set(market_status["strategy_ready_symbols"]) == set(symbols),
                "strategy_required_closed_candles": 55,
                "market_filter": {
                    "adx_period": self.settings.adx_period,
                    "adx_min": self.settings.adx_min,
                    "atr_period": self.settings.atr_period,
                    "atr_min_pct": self.settings.atr_min_pct,
                    "atr_max_pct": self.settings.atr_max_pct,
                },
                "win_rate": trader_snapshot.get("win_rate", 0.0),
                "sharpe_ratio": trader_snapshot.get("sharpe_ratio", 0.0),
                "max_drawdown": trader_snapshot.get("max_drawdown", 0.0),
            }
            last_error = self.last_error_log
            last_warning = self.last_warning
        user_id = self.settings.telegram_chat_id or "local"
        persisted_state = self.supabase.select_runtime_state(user_id)
        database_sync: dict[str, Any] = {
            "available": bool(persisted_state),
            "updated_at": persisted_state.get("updated_at") if persisted_state else None,
            "age_seconds": None,
            "state_matches_live": False,
            "symbols_match": False,
        }
        if persisted_state:
            try:
                persisted_at = datetime.fromisoformat(str(persisted_state["updated_at"]).replace("Z", "+00:00"))
                database_sync["age_seconds"] = max(0.0, (datetime.now(timezone.utc) - persisted_at).total_seconds())
            except (KeyError, TypeError, ValueError):
                database_sync["age_seconds"] = None
            persisted_symbols = set(persisted_state.get("selected_symbols") or [])
            database_sync["symbols_match"] = persisted_symbols == set(symbols)
            database_sync["state_matches_live"] = (
                bool(persisted_state.get("runtime_started")) == bool(overview["runtime_started"])
                and bool(persisted_state.get("websocket_connected")) == bool(overview["websocket_connected"])
                and database_sync["symbols_match"]
            )
            overview["database_sync"] = database_sync
        
        with self._lock:
            all_logs = list(self.recent_logs)
        errors = [l for l in all_logs if l.get("level") in ("ERROR", "CRITICAL")][:100]
        warnings = [l for l in all_logs if l.get("level") == "WARNING"][:100]

        user_id = self.settings.telegram_chat_id or "local"
        recent_signals = self.supabase.select_recent_signals(user_id, limit=50)
        recent_positions = self.supabase.select_recent_positions(user_id, limit=50)
        events = self.supabase.select_recent_events(user_id, limit=50)

        return {
            "overview": overview,
            "open_positions": trader_snapshot["open_positions"],
            "last_error": last_error,
            "last_warning": last_warning,
            "errors": errors,
            "warnings": warnings,
            "recent_signals": recent_signals,
            "recent_positions": recent_positions,
            "events": events,
            "logs": all_logs[-100:][::-1],
        }

    def history_snapshot(self) -> dict[str, Any]:
        """Returns heavy historical data for background loading."""
        user_id = self.settings.telegram_chat_id or "local"
        with self._lock:
            recent_logs = list(self.recent_logs)[-100:][::-1]
        return {
            "recent_signals": self.supabase.select_recent_signals(user_id, limit=50),
            "recent_positions": self.supabase.select_recent_positions(user_id, limit=50),
            "events": self.supabase.select_recent_events(user_id, limit=50),
            "logs": recent_logs,
        }

    def _on_price(self, symbol: str, price: float) -> None:
        symbol = self._normalise_symbol(symbol)
        with self._lock:
            if symbol not in self.trader.selected_symbols:
                return
            self.last_event_at = datetime.now(timezone.utc)
            closed = self.trader.on_price(symbol, price)
            now = time.time()
            if now - self._last_price_log_at.get(symbol, 0) >= 60:
                self._last_price_log_at[symbol] = now
                logger.info("market_price_update symbol=%s price=%.8f open_position=%s", symbol, price, bool(self.trader.position_for_symbol(symbol)))
            for position in closed:
                self.closed_trade_count += 1
                self._persist_closed_position(position)
                close_payload = position.to_dict()
                logger.info("virtual_trade_closed %s", json.dumps(close_payload, ensure_ascii=False, default=str))
                self.telegram.alert(
                    f"انتهت الصفقة الافتراضية {position.symbol}\n"
                    f"السبب: {position.close_reason}\n"
                    f"الدخول: {position.entry_price:.8f}\n"
                    f"الخروج: {position.exit_price:.8f}\n"
                    f"النتيجة الافتراضية: {position.realized_pnl:.8f} USDT\n"
                    f"أداء اليوم: {self.trader.realized_pnl_today:.8f} USDT"
                )
                self._log_event("virtual_position_closed", close_payload)

    def _on_closed_candle(self, symbol: str, interval: str, candle: dict[str, Any]) -> None:
        symbol = self._normalise_symbol(symbol)
        with self._lock:
            if symbol not in self.trader.selected_symbols:
                return
            self.last_event_at = datetime.now(timezone.utc)
            if interval == self.settings.execution_timeframe:
                self.cycle_count += 1
                logger.info("strategy_cycle_start symbol=%s interval=%s price=%.8f", symbol, interval, candle["close"])
                
                # Check for signal confirmation on 15m (trigger timeframe) if it's different from execution
                trigger_data = None
                if self.settings.trigger_timeframe != self.settings.execution_timeframe:
                    trigger_candles = self.market.candles(symbol, self.settings.trigger_timeframe)
                    if len(trigger_candles) >= 55:
                        trigger_data = list(trigger_candles)
                
                execution_candles = self.market.candles(symbol, self.settings.execution_timeframe)
                higher_candles = self.market.candles(symbol, self.settings.higher_timeframe)
                
                if len(execution_candles) < 55 or len(higher_candles) < 55:
                    logger.info("strategy_cycle_skipped symbol=%s reason=insufficient_history", symbol)
                    self._record_decision({"symbol": symbol, "decision": "DATA_NOT_READY", "rejection_reason": "History incomplete"})
                    return
                
                # Fix: Pass settings values as keyword arguments
                decision_obj, diag = evaluate_signal_diagnostics(
                    symbol=symbol,
                    execution_candles=list(execution_candles),
                    higher_candles=list(higher_candles),
                    stop_loss_pct=self.settings.stop_loss_pct,
                    take_profit_r_multiple=self.settings.take_profit_r_multiple,
                    adx_period=self.settings.adx_period,
                    adx_min=self.settings.adx_min,
                    atr_period=self.settings.atr_period,
                    atr_min_pct=self.settings.atr_min_pct,
                    atr_max_pct=self.settings.atr_max_pct
                )
                decision = {
                    "symbol": symbol,
                    "decision": "BUY" if decision_obj else diag.get("rejection_reason", "NO_SIGNAL"),
                    "signal_payload": decision_obj.to_dict() if decision_obj else None,
                    "indicator_metrics": diag,
                    **diag
                }
                self._record_decision(decision)
                
                if decision.get("decision") == "BUY":
                    self.signal_count += 1
                    signal_payload = decision.get("signal_payload")
                    if signal_payload:
                        signal = Signal.from_dict(signal_payload)
                        self.last_signal = signal
                        self._persist_signal(signal)
                        position = self.trader.open_position(symbol, signal.entry_price, signal.stop_loss, signal.take_profit)
                        if position:
                            self._persist_open_position(position)
                            logger.info("virtual_trade_opened symbol=%s entry=%.8f", symbol, signal.entry_price)
                            self.telegram.alert(
                                f"توصية شراء جديدة: {symbol}\n"
                                f"السعر: {signal.entry_price:.8f}\n"
                                f"الوقف: {signal.stop_loss:.8f}\n"
                                f"الهدف: {signal.take_profit:.8f}\n"
                                f"السبب: {signal.reason}"
                            )
                elif decision.get("decision") != "DATA_NOT_READY":
                    self.rejected_signal_count += 1
                
                self._persist_runtime_state()

    def _persist_runtime_state(self) -> None:
        user_id = self.settings.telegram_chat_id or "local"
        row = {
            "user_id": user_id,
            "runtime_started": self._started,
            "websocket_connected": self.market.connected,
            "live_data_available": self.market.live_data_available,
            "live_data_source": self.market.live_data_source,
            "selected_symbols": sorted(self.trader.selected_symbols),
            "cycle_count": self.cycle_count,
            "signal_count": self.signal_count,
            "closed_trade_count": self.closed_trade_count,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        self.supabase.upsert("runtime_state", row, "user_id")

    def start(self) -> None:
        with self._lock:
            if self._started and self.is_alive():
                return
            self._started = True
            self._stop.clear()
            self._load_persisted_settings()
            self.market.start()
            self.telegram.start()
            self._summary_thread = threading.Thread(target=self._run_forever, name="bot-runtime", daemon=True)
            self._summary_thread.start()
            logger.info("runtime_started")

    def is_alive(self) -> bool:
        return bool(self._summary_thread and self._summary_thread.is_alive())

    def stop(self) -> None:
        with self._lock:
            self._started = False
            self._stop.set()
            self.market.stop()
            self.telegram.stop()
            if self._summary_thread:
                self._summary_thread.join(timeout=5)
            logger.info("runtime_stopped")

    def _run_forever(self) -> None:
        last_persist = 0
        while not self._stop.is_set():
            try:
                now_ts = time.time()
                with self._lock:
                    # Persist state less frequently to reduce lock contention
                    if now_ts - last_persist >= 300:
                        self._persist_runtime_state()
                        last_persist = now_ts

                    # Watchdog: If no live data for 5 minutes, force reconnect
                    if self.market.live_data_available:
                        last_msg = self.market.status_snapshot().get("last_message_at") or self.market.status_snapshot().get("last_rest_message_at")
                        if last_msg:
                            age = (datetime.now(timezone.utc) - datetime.fromisoformat(str(last_msg))).total_seconds()
                            if age > 300:
                                logger.warning("runtime_watchdog_triggered reason=stale_data age=%ds", age)
                                self.market._force_reconnect()
            except Exception as exc:
                logger.error("runtime_loop_error error=%s", exc)
            self._stop.wait(60)

    def status_text(self) -> str:
        with self._lock:
            ms = self.market.status_snapshot()
            ready = sorted(ms["strategy_ready_symbols"])
            return (
                f"حالة النظام\n"
                f"مرحلة البدء: {ms['startup_stage']}\n"
                f"إعادة محاولة جلب الشموع: {'مطلوبة' if ms['next_bootstrap_retry_at'] else 'غير مطلوب؛ التهيئة مكتملة'}\n"
                f"مصدر بيانات السوق: {'متصل' if self.market.live_data_available else 'غير متصل'}\n"
                f"آخر حدث: {self.last_event_at.isoformat() if self.last_event_at else 'لا يوجد'}\n"
                f"العملات المضافة: {', '.join(sorted(self.trader.selected_symbols))}\n"
                f"الصفقات المفتوحة: {len(self.trader.open_positions)}/{self.settings.max_concurrent_positions}\n"
                f"التكاملات الناقصة: {', '.join(self.settings.missing_integrations()) or 'لا يوجد'}\n"
                f"دورات الاستراتيجية: {self.cycle_count} | الإشارات: {self.signal_count}\n"
                f"العملات الجاهزة للتحليل: {', '.join(ready) or 'لا يوجد'}\n"
                f"التنفيذ: توصيات ومتابعة افتراضية فقط، بلا أوامر Binance"
            )

    def prices_text(self) -> str:
        with self._lock:
            lines = ["الأسعار الحية:"]
            for symbol in sorted(self.trader.selected_symbols):
                price = self.trader.last_prices.get(symbol)
                lines.append(f"{symbol}: {f'{price:.8f}' if price else 'بانتظار البيانات'}")
            return "\n".join(lines)

    def performance_text(self) -> str:
        with self._lock:
            stats = self.trader.status_snapshot()
            return (
                f"أداء النظام (افتراضي)\n"
                f"PnL اليوم: {stats['realized_pnl_today']:.2f} USDT\n"
                f"نسبة الربح: {stats.get('win_rate', 0.0)*100:.1f}%\n"
                f"معدل شارب: {stats.get('sharpe_ratio', 0.0):.2f}\n"
                f"أقصى تراجع: {stats.get('max_drawdown', 0.0)*100:.1f}%\n"
                f"إجمالي الصفقات: {self.closed_trade_count}\n"
                f"رأس المال النشط: {stats['total_capital']:.2f} USDT"
            )

    def positions_text(self) -> str:
        with self._lock:
            positions = self.trader.open_positions
            if not positions:
                return "لا توجد صفقات مفتوحة حالياً."
            lines = ["الصفقات المفتوحة:"]
            for p in positions:
                pnl = p.unrealized_pnl(self.trader.last_prices.get(p.symbol, p.entry_price))
                lines.append(f"{p.symbol}: دخول {p.entry_price:.8f} | PnL: {pnl:.2f} USDT")
            return "\n".join(lines)

    def coins_text(self) -> str:
        with self._lock:
            symbols = sorted(self.trader.selected_symbols)
            if not symbols:
                return "لم يتم إضافة أي عملات بعد."
            lines = ["العملات المراقبة:"]
            for s in symbols:
                cap = self.trader.capital_by_symbol.get(s, 0.0)
                lines.append(f"{s}: {cap:.2f} USDT")
            return "\n".join(lines)

    def manage_coin(self, symbol: str, capital: float | None = None) -> str:
        symbol = self._normalise_symbol(symbol)
        with self._lock:
            if capital is None:
                if symbol in self.trader.selected_symbols:
                    self.trader.remove_symbol(symbol)
                    self._persist_settings()
                    return f"تم حذف العملة {symbol} بنجاح."
                return f"العملة {symbol} غير موجودة."
            else:
                self.trader.add_symbol(symbol)
                self.trader.set_capital(symbol, capital)
                self._persist_settings()
                self.market.start()  # Ensure market data client is updated
                return f"تم إضافة {symbol} برأس مال {capital} USDT."

    def telegram_keyboard(self) -> list[list[str]]:
        with self._lock:
            symbols = sorted(self.trader.selected_symbols)
            rows = []
            for i in range(0, len(symbols), 2):
                rows.append(symbols[i:i+2])
            return rows

    def symbol_status_text(self, symbol: str) -> str:
        symbol = self._normalise_symbol(symbol)
        with self._lock:
            if symbol not in self.trader.selected_symbols:
                return f"العملة {symbol} غير مراقبة."
            price = self.trader.last_prices.get(symbol)
            cap = self.trader.capital_by_symbol.get(symbol, 0.0)
            decision = self.last_decision_by_symbol.get(symbol, {})
            return (
                f"حالة {symbol}\n"
                f"السعر: {f'{price:.8f}' if price else 'بانتظار البيانات'}\n"
                f"رأس المال: {cap:.2f} USDT\n"
                f"آخر قرار: {decision.get('decision', 'لا يوجد')}\n"
                f"السبب: {decision.get('rejection_reason', '—')}"
            )
