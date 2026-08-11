from __future__ import annotations

import json
import logging
import re
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
        self.last_decision: dict[str, Any] | None = None
        self.cycle_count = 0
        self.signal_count = 0
        self.rejected_signal_count = 0
        self.closed_trade_count = 0
        self._last_price_log_at: dict[str, float] = {}
        self.market = BinanceMarketData(self.settings, self._on_price, self._on_closed_candle)
        self.telegram = TelegramBot(
            self.settings,
            get_status=self.status_text,
            get_prices=self.prices_text,
            get_performance=self.performance_text,
            get_positions=self.positions_text,
            manage_coin=self.manage_coin,
            get_keyboard=self.telegram_keyboard,
            get_symbol_status=self.symbol_status_text,
        )

    @staticmethod
    def _normalise_symbol(symbol: str) -> str:
        return re.sub(r"[^A-Z0-9]", "", symbol.upper())

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
            }
            signal = evaluate_signal(
                symbol,
                execution,
                higher,
                stop_loss_pct=self.settings.stop_loss_pct,
                take_profit_r_multiple=self.settings.take_profit_r_multiple,
            )
            if signal is None:
                decision["decision"] = "NO_SIGNAL"
                self.last_decision = decision
                logger.info("strategy_cycle %s", json.dumps(decision, ensure_ascii=False, default=str))
                self._log_event("strategy_cycle", decision)
                return
            if self.trader.last_signal_at.get(symbol) == signal.candle_open_time:
                decision["decision"] = "DUPLICATE_SIGNAL_IGNORED"
                self.last_decision = decision
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
            [{"text": "🪙 إدارة العملات ورأس المال"}],
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
        return "\n".join(lines)

    def prices_text(self) -> str:
        symbols = sorted(self.trader.selected_symbols)
        if not symbols:
            return "لا توجد عملات للعرض. أضف عملة ورأس مالها من الزر الديناميكي أولاً."
        lines = ["الأسعار الحية للعملات المضافة فقط:"]
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
        ws = "متصل" if self.market.connected else "غير متصل"
        last_event = self.last_event_at.isoformat() if self.last_event_at else "لا يوجد"
        missing = ", ".join(snapshot.get("selected_symbols", [])) or "لا توجد عملات مضافة"
        integration_missing = ", ".join(self.settings.missing_integrations()) or "لا يوجد"
        return (
            "حالة النظام\n"
            f"Binance WebSocket: {ws}\n"
            f"آخر حدث: {last_event}\n"
            f"العملات المضافة: {missing}\n"
            f"الصفقات المفتوحة: {len(snapshot['open_positions'])}/{self.settings.max_concurrent_positions}\n"
            f"التكاملات الناقصة: {integration_missing}\n"
            f"دورات الاستراتيجية: {self.cycle_count} | الإشارات: {self.signal_count}\n"
            "التنفيذ: توصيات ومتابعة افتراضية فقط، بلا أوامر Binance"
        )

    def _summary_loop(self) -> None:
        while not self._stop.wait(60):
            with self._lock:
                snapshot = self.trader.snapshot()
                snapshot.update({
                    "websocket_connected": self.market.connected,
                    "last_event_at": self.last_event_at.isoformat() if self.last_event_at else None,
                    "strategy": "ema_breakout_4h_filter_v1",
                    "metrics": {
                        "cycles": self.cycle_count,
                        "signals": self.signal_count,
                        "rejected_signals": self.rejected_signal_count,
                        "closed_trades": self.closed_trade_count,
                    },
                    "last_decision": self.last_decision,
                    "last_signal": self.last_signal.to_dict() if self.last_signal else None,
                })
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
            "last_event_at": self.last_event_at.isoformat() if self.last_event_at else None,
            "open_positions": len(self.trader.positions),
            "selected_symbols": sorted(self.trader.selected_symbols),
            "capital_by_symbol": self.trader.capital_by_symbol,
            "cycles": self.cycle_count,
            "signals": self.signal_count,
            "missing_integrations": self.settings.missing_integrations(),
        }
