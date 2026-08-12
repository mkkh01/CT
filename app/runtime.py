from __future__ import annotations

import json
import logging
from collections import deque
import re
import threading
import time
from datetime import datetime, timezone
from typing import Any

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
        with self._lock:
            trader_snapshot = self.trader.snapshot()
            symbols = sorted(self.trader.selected_symbols)
            coins = [
                {
                    "symbol": symbol,
                    "capital_usdt": self.trader.capital_by_symbol.get(symbol, 0.0),
                    "price": self.trader.last_prices.get(symbol),
                    "position_open": bool(self.trader.position_for_symbol(symbol)),
                }
                for symbol in symbols
            ]
            market_status = self.market.status_snapshot()
            for coin in coins:
                coin["market"] = market_status["symbols"].get(coin["symbol"], {})
                decision = self.last_decision_by_symbol.get(coin["symbol"])
                if decision:
                    metrics = decision.get("indicator_metrics") or {}
                    coin["analysis"] = {
                        "decision": decision.get("decision"),
                        "chart_regime": decision.get("market_regime"),
                        "chart_regime_label": decision.get("market_regime_label"),
                        "chart_regime_1h": decision.get("chart_regime_1h"),
                        "chart_regime_1h_label": decision.get("chart_regime_1h_label"),
                        "chart_regime_4h": decision.get("chart_regime_4h"),
                        "chart_regime_4h_label": decision.get("chart_regime_4h_label"),
                        "candle_pattern": decision.get("candle_pattern"),
                        "candle_pattern_label": decision.get("candle_pattern_label"),
                        "candle_direction": decision.get("candle_direction"),
                        "candle_pattern_1h": decision.get("candle_pattern_1h"),
                        "candle_direction_1h": decision.get("candle_direction_1h"),
                        "candle_pattern_4h": decision.get("candle_pattern_4h"),
                        "candle_direction_4h": decision.get("candle_direction_4h"),
                        "rejection_reason": decision.get("rejection_reason"),
                        "rejection_detail": decision.get("rejection_detail"),
                        "adx": metrics.get("adx"),
                        "atr_pct": metrics.get("atr_pct"),
                    }
                else:
                    coin["analysis"] = None
            overview = {
                "service": "CT Binance Spot Live Recommendations",
                "execution": "disabled",
                "runtime_started": self._started,
                "websocket_connected": self.market.connected,
                "live_data_available": self.market.live_data_available,
                "live_data_source": self.market.live_data_source,
                "last_event_at": self.last_event_at.isoformat() if self.last_event_at else None,
                "strategy": "ema_breakout_4h_filter_v1",
                "timeframes": {"execution": self.settings.execution_timeframe, "higher": self.settings.higher_timeframe},
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
            }
            recent_logs = list(self.recent_logs)[-250:][::-1]
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
        return {
            "overview": overview,
            "open_positions": trader_snapshot["open_positions"],
            "recent_signals": self.supabase.select_recent_signals(user_id, limit=50),
            "recent_positions": self.supabase.select_recent_positions(user_id, limit=50),
            "events": self.supabase.select_recent_events(user_id, limit=50),
            "logs": recent_logs[:50],
            "errors": [item for item in recent_logs if item["level"] in ("ERROR", "CRITICAL")],
            "warnings": [item for item in recent_logs if item["level"] == "WARNING"],
            "persisted_runtime_state": persisted_state,
            "last_error": last_error,
            "last_warning": last_warning,
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
        if interval != self.settings.execution_timeframe or symbol not in self.trader.selected_symbols:
            return
        with self._lock:
            self.last_event_at = datetime.now(timezone.utc)
            self.cycle_count += 1
            execution = self.market.candles(symbol, self.settings.execution_timeframe)
            higher = self.market.candles(symbol, self.settings.higher_timeframe)
            market_state = self.market.status_snapshot()["symbols"].get(symbol, {})
            decision: dict[str, Any] = {
                "cycle": self.cycle_count,
                "symbol": symbol,
                "strategy": "ema_breakout_4h_filter_v1",
                "timeframe": interval,
                "candle_open_time": candle.get("open_time"),
                "closed_candles_1h": len(execution),
                "closed_candles_4h": len(higher),
                "price": candle.get("close"),
                "selected": True,
                "signal": False,
                "position_action": "none",
                "data_ready": bool(market_state.get("ready_for_strategy")),
                "data_readiness_reason": "ready" if market_state.get("ready_for_strategy") else "waiting_for_55_closed_candles_on_1h_and_4h",
            }
            if not market_state.get("ready_for_strategy"):
                decision["decision"] = "DATA_NOT_READY"
                self._record_decision(decision)
                logger.info("strategy_cycle %s", json.dumps(decision, ensure_ascii=False, default=str))
                self._log_event("strategy_cycle", decision)
                return
            signal, diagnostics = evaluate_signal_diagnostics(
                symbol,
                execution,
                higher,
                stop_loss_pct=self.settings.stop_loss_pct,
                take_profit_r_multiple=self.settings.take_profit_r_multiple,
                adx_period=self.settings.adx_period,
                adx_min=self.settings.adx_min,
                atr_period=self.settings.atr_period,
                atr_min_pct=self.settings.atr_min_pct,
                atr_max_pct=self.settings.atr_max_pct,
            )
            decision.update({
                "market_regime": diagnostics.get("chart_regime"),
                "market_regime_label": diagnostics.get("chart_regime_label"),
                "chart_regime_1h": diagnostics.get("chart_regime_1h"),
                "chart_regime_1h_label": diagnostics.get("chart_regime_1h_label"),
                "chart_regime_4h": diagnostics.get("chart_regime_4h"),
                "chart_regime_4h_label": diagnostics.get("chart_regime_4h_label"),
                "candle_pattern": diagnostics.get("candle_pattern"),
                "candle_pattern_label": diagnostics.get("candle_pattern_label"),
                "candle_direction": diagnostics.get("candle_direction"),
                "candle_pattern_1h": diagnostics.get("candle_pattern_label_1h"),
                "candle_direction_1h": diagnostics.get("candle_direction_1h"),
                "candle_pattern_4h": diagnostics.get("candle_pattern_label_4h"),
                "candle_direction_4h": diagnostics.get("candle_direction_4h"),
                "indicator_metrics": diagnostics,
            })
            if signal is None:
                decision["decision"] = "MARKET_FILTER_REJECTED" if diagnostics.get("rejection_reason") in {
                    "SIDEWAYS_ADX_LOW",
                    "SIDEWAYS_ATR_LOW",
                    "EMA_ALIGNMENT_SIDEWAYS",
                    "VOLATILITY_TOO_HIGH",
                    "BEARISH_DIRECTIONAL_MOVEMENT",
                } else "NO_SIGNAL"
                decision["rejection_reason"] = diagnostics.get("rejection_reason")
                decision["rejection_detail"] = diagnostics.get("rejection_detail")
                self._record_decision(decision)
                logger.info("strategy_cycle %s", json.dumps(decision, ensure_ascii=False, default=str))
                self._log_event("strategy_cycle", decision)
                return
            if self.trader.last_signal_at.get(symbol) == signal.candle_open_time:
                decision["decision"] = "DUPLICATE_SIGNAL_IGNORED"
                self._record_decision(decision)
                logger.info("strategy_cycle %s", json.dumps(decision, ensure_ascii=False, default=str))
                return

            self.signal_count += 1
            self.last_signal = signal
            self._persist_signal(signal)
            signal_payload = signal.to_dict()
            decision.update({"signal": True, "decision": "SIGNAL_GENERATED", "signal_payload": signal_payload})
            position, status = self.trader.open_from_signal(signal)
            if position:
                decision["position_action"] = "VIRTUAL_POSITION_OPENED"
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
                self.rejected_signal_count += 1
                decision.update({"decision": "SIGNAL_REJECTED", "rejection_reason": status})
                self.telegram.alert(f"إشارة {signal.symbol} موجودة، لكن لم تُفتح متابعة افتراضية.\nالسبب: {status}")
            self.last_decision = decision
            logger.info("strategy_cycle %s", json.dumps(decision, ensure_ascii=False, default=str))
            self._log_event("strategy_decision", decision)

    def manage_coin(self, command: str) -> str:
        if command == "list":
            return self.coins_text()
        parts = command.split(":")
        action = parts[0]
        symbol = self._normalise_symbol(parts[1]) if len(parts) > 1 else ""
        with self._lock:
            if not symbol:
                return "رمز العملة غير صالح."
            if action in ("add", "update"):
                try:
                    amount = float(parts[2])
                except (IndexError, ValueError):
                    return "أرسل الصيغة: أضف XRPUSDT 50"
                if amount <= 0:
                    return "رأس المال يجب أن يكون أكبر من صفر."
                self.trader.set_capital(symbol, amount)
                self.market.update_symbols(sorted(self.trader.selected_symbols))
                self._persist_settings()
                if self._started:
                    self.market.restart()
                verb = "إضافة" if action == "add" else "تعديل"
                return f"تمت {verb} العملة {symbol} برأس مال {amount:.8f} USDT. بدأت متابعة السعر والإشارات لها."
            if action == "remove":
                if not self.trader.remove_symbol(symbol):
                    return f"لا يمكن حذف {symbol} أثناء وجود صفقة افتراضية مفتوحة."
                self.market.update_symbols(sorted(self.trader.selected_symbols))
                self._persist_settings()
                if self._started:
                    self.market.restart()
                return f"تم حذف {symbol} وإيقاف متابعة سعرها وإشاراتها."
            return "أمر غير معروف. استخدم: أضف XRPUSDT 50 أو عدّل XRPUSDT 75 أو احذف XRPUSDT."

    def coins_text(self) -> str:
        symbols = sorted(self.trader.selected_symbols)
        if not symbols:
            return "لا توجد عملات مضافة. اضغط إدارة العملات ورأس المال ثم أرسل مثلاً: أضف XRPUSDT 50"
        lines = ["العملات التي أضافها المستخدم:"]
        for symbol in symbols:
            price = self.trader.last_prices.get(symbol)
            position = self.trader.position_for_symbol(symbol)
            state = "صفقة افتراضية مفتوحة" if position else "لا توجد صفقة مفتوحة"
            price_text = f"{price:.8f}" if price is not None else "بانتظار WebSocket"
            lines.append(f"{symbol} | رأس المال: {self.trader.capital_by_symbol.get(symbol, 0):.8f} USDT | السعر: {price_text} | {state}")
        return "\n".join(lines)

    def telegram_keyboard(self) -> dict[str, Any]:
        rows: list[list[dict[str, str]]] = [
            [{"text": "➕ إضافة عملة"}, {"text": "🧾 العملات المضافة"}],
            [{"text": "📈 الأسعار الحية"}, {"text": "📊 أداء النظام"}],
            [{"text": "📂 الصفقات"}, {"text": "ℹ️ الحالة"}],
        ]
        symbols = sorted(self.trader.selected_symbols)
        if symbols:
            for index in range(0, len(symbols), 2):
                rows.append([{"text": f"🔎 {symbol}"} for symbol in symbols[index : index + 2]])
        return {"keyboard": rows, "resize_keyboard": True, "is_persistent": True}

    def symbol_status_text(self, symbol: str) -> str:
        symbol = self._normalise_symbol(symbol)
        if symbol not in self.trader.selected_symbols:
            return f"{symbol} غير موجودة في قائمة المستخدم. أضفها من زر إدارة العملات ورأس المال."
        price = self.trader.last_prices.get(symbol)
        position = self.trader.position_for_symbol(symbol)
        signal = self.last_signal if self.last_signal and self.last_signal.symbol == symbol else None
        lines = [
            f"حالة {symbol}",
            f"رأس المال: {self.trader.capital_by_symbol.get(symbol, 0):.8f} USDT",
            f"السعر الحي: {price:.8f}" if price is not None else "السعر الحي: بانتظار Binance WebSocket",
            f"المتابعة الافتراضية: {'مفتوحة' if position else 'غير مفتوحة'}",
        ]
        if position:
            lines.append(f"الدخول {position.entry_price:.8f} | الوقف {position.stop_loss:.8f} | الهدف {position.take_profit:.8f}")
        if signal:
            lines.append(f"آخر إشارة: دخول {signal.entry_price:.8f} | {signal.reason}")
        decision = self.last_decision_by_symbol.get(symbol)
        if decision:
            metrics = decision.get("indicator_metrics") or {}
            lines.extend([
                f"حالة الشارت: {decision.get('market_regime_label') or decision.get('market_regime') or 'غير متاح'}",
                f"شمعة 1H: {decision.get('candle_pattern_1h') or decision.get('candle_pattern_label') or decision.get('candle_pattern') or 'غير متاح'} ({decision.get('candle_direction_1h') or decision.get('candle_direction') or '—'})",
                f"شمعة 4H: {decision.get('candle_pattern_4h') or 'غير متاح'} ({decision.get('candle_direction_4h') or '—'})",
                f"ADX: {float(metrics['adx']):.2f}" if metrics.get("adx") is not None else "ADX: غير متاح",
                f"ATR/السعر: {float(metrics['atr_pct']) * 100:.3f}%" if metrics.get("atr_pct") is not None else "ATR/السعر: غير متاح",
                f"سبب القرار: {decision.get('rejection_detail') or decision.get('rejection_reason') or decision.get('decision') or '—'}",
            ])
        return "\n".join(lines)

    def prices_text(self) -> str:
        symbols = sorted(self.trader.selected_symbols)
        if not symbols:
            return "لا توجد عملات للعرض. أضف عملة ورأس مالها من الزر الديناميكي أولاً."
        market_status = self.market.status_snapshot()
        lines = [
            "الأسعار الحية للعملات المضافة فقط:",
            f"مرحلة النظام: {market_status.get('startup_stage', 'unknown')}",
            f"آخر شمعة مغلقة: {market_status.get('last_closed_candle') or 'بانتظار WebSocket'}",
        ]
        for symbol in symbols:
            price = self.trader.last_prices.get(symbol)
            lines.append(f"{symbol}: {price:.8f}" if price is not None else f"{symbol}: بانتظار WebSocket")
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
            f"حالة الحد اليومي: {'متوقف' if snapshot['daily_loss_limit_hit'] else 'نشط'}\n"
            f"دورات الاستراتيجية: {self.cycle_count} | الإشارات: {self.signal_count} | الصفقات المغلقة: {self.closed_trade_count}"
        )

    def positions_text(self) -> str:
        positions = list(self.trader.positions.values())
        if not positions:
            return "لا توجد صفقات افتراضية مفتوحة للعملات المضافة."
        lines = ["الصفقات الافتراضية المفتوحة للعملات المضافة:"]
        for position in positions:
            current = self.trader.last_prices.get(position.symbol, position.entry_price)
            pnl = (current - position.entry_price) * position.quantity
            lines.append(
                f"{position.symbol} | رأس المال {position.capital_allocated:.8f} | دخول {position.entry_price:.8f} | الآن {current:.8f} | "
                f"وقف {position.stop_loss:.8f} | هدف {position.take_profit:.8f} | PnL {pnl:.8f} USDT"
            )
        return "\n".join(lines)

    def status_text(self) -> str:
        snapshot = self.trader.snapshot()
        market_status = self.market.status_snapshot()
        live_source = market_status.get("live_data_source") or "none"
        live_available = bool(market_status.get("live_data_available"))
        ws = "متصل" if self.market.connected else ("REST fallback حي" if live_available and live_source == "rest_polling_fallback" else "غير متصل")
        last_event = self.last_event_at.isoformat() if self.last_event_at else "لا يوجد"
        missing = ", ".join(snapshot.get("selected_symbols", [])) or "لا توجد عملات مضافة"
        integration_missing = ", ".join(self.settings.missing_integrations()) or "لا يوجد"
        ready_symbols = ", ".join(market_status.get("strategy_ready_symbols", [])) or "لا توجد عملات جاهزة بعد"
        next_retry = market_status.get("next_bootstrap_retry_at") or "غير مطلوب؛ التهيئة مكتملة"
        return (
            "حالة النظام\n"
            f"مرحلة البدء: {market_status.get('startup_stage', 'unknown')}\n"
            f"إعادة محاولة جلب الشموع: {next_retry}\n"
            f"مصدر بيانات السوق: {ws}\n"
            f"آخر حدث: {last_event}\n"
            f"العملات المضافة: {missing}\n"
            f"الصفقات المفتوحة: {len(snapshot['open_positions'])}/{self.settings.max_concurrent_positions}\n"
            f"التكاملات الناقصة: {integration_missing}\n"
            f"دورات الاستراتيجية: {self.cycle_count} | الإشارات: {self.signal_count}\n"
            f"العملات الجاهزة للتحليل: {ready_symbols}\n"
            "التنفيذ: توصيات ومتابعة افتراضية فقط، بلا أوامر Binance"
        )

    def _persist_runtime_state(self, market_status: dict[str, Any], snapshot: dict[str, Any]) -> None:
        user_id = self.settings.telegram_chat_id or "local"
        row = {
            "user_id": user_id,
            "runtime_started": self._started,
            "websocket_connected": bool(market_status.get("connected")),
            "live_data_available": bool(market_status.get("live_data_available")),
            "live_data_source": market_status.get("live_data_source"),
            "startup_stage": market_status.get("startup_stage") or "idle",
            "websocket_last_message_at": market_status.get("last_message_at"),
            "websocket_connected_at": market_status.get("connected_at"),
            "websocket_last_error": market_status.get("last_ws_error"),
            "websocket_last_close_code": str(market_status.get("last_ws_close_code")) if market_status.get("last_ws_close_code") is not None else None,
            "websocket_last_close_reason": market_status.get("last_ws_close_reason"),
            "websocket_active_stream_url": market_status.get("active_stream_url"),
            "selected_symbols": snapshot.get("selected_symbols", []),
            "capital_by_symbol": snapshot.get("capital_by_symbol", {}),
            "strategy_ready_symbols": market_status.get("strategy_ready_symbols", []),
            "market_status": market_status,
            "metrics": snapshot.get("metrics", {}),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        self.supabase.upsert_runtime_state(row)

    def _emit_summary_cycle(self) -> None:
        with self._lock:
            snapshot = self.trader.snapshot()
            market_status = self.market.status_snapshot()
            snapshot.update({
                "websocket_connected": self.market.connected,
                "live_data_available": self.market.live_data_available,
                "live_data_source": self.market.live_data_source,
                "startup_stage": market_status.get("startup_stage"),
                "last_event_at": self.last_event_at.isoformat() if self.last_event_at else None,
                "strategy": "ema_breakout_4h_filter_v1",
                "strategy_ready_symbols": market_status.get("strategy_ready_symbols", []),
                "metrics": {
                    "cycles": self.cycle_count,
                    "signals": self.signal_count,
                    "rejected_signals": self.rejected_signal_count,
                    "closed_trades": self.closed_trade_count,
                },
                "last_decision": self.last_decision,
                "last_decision_by_symbol": self.last_decision_by_symbol,
                "last_signal": self.last_signal.to_dict() if self.last_signal else None,
                "market_status": market_status,
            })
            logger.info("summary_cycle %s", json.dumps(snapshot, ensure_ascii=False, default=str))
            self.redis.set_json("bot:summary", snapshot, ex=300)
            self._persist_runtime_state(market_status, snapshot)
            self._log_event("summary_cycle", snapshot)

    def _summary_loop(self) -> None:
        # Self-healing watchdog: if live data is missing for too long, restart market connection.
        last_live_at = time.time()
        while not self._stop.wait(60):
            self._emit_summary_cycle()
            
            # Check liveness
            status = self.market.status_snapshot()
            if status.get("live_data_available"):
                last_live_at = time.time()
            else:
                missing_duration = time.time() - last_live_at
                if missing_duration > 300: # 5 minutes
                    logger.warning("runtime_watchdog_restarting_market reason=no_live_data duration_seconds=%.1f", missing_duration)
                    self.market.restart()
                    last_live_at = time.time() # Reset to avoid immediate repeat

    def is_alive(self) -> bool:
        # Check if the main background threads are running.
        return bool(
            self._started and
            self.market._thread and self.market._thread.is_alive() and
            self._summary_thread and self._summary_thread.is_alive()
        )

    def start(self) -> None:
        if self.is_alive():
            return
        self._load_persisted_settings()
        self.market.update_symbols(sorted(self.trader.selected_symbols))
        self.market.start()
        self.telegram.start()
        self._stop.clear()
        self._started = True
        self._emit_summary_cycle()
        self._summary_thread = threading.Thread(target=self._summary_loop, name="summary-cycle", daemon=True)
        self._summary_thread.start()
        logger.info("runtime_started symbols=%s capital_by_symbol=%s strategy=ema_breakout_4h_filter_v1", sorted(self.trader.selected_symbols), self.trader.capital_by_symbol)

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
            "live_data_available": self.market.live_data_available,
            "live_data_source": self.market.live_data_source,
            "last_event_at": self.last_event_at.isoformat() if self.last_event_at else None,
            "open_positions": len(self.trader.positions),
            "selected_symbols": sorted(self.trader.selected_symbols),
            "capital_by_symbol": self.trader.capital_by_symbol,
            "cycles": self.cycle_count,
            "signals": self.signal_count,
            "missing_integrations": self.settings.missing_integrations(),
            "market_status": self.market.status_snapshot(),
        }
