from __future__ import annotations

import logging
import re
import threading
import time
from typing import Any, Callable, Optional

import requests

from .config import Settings

logger = logging.getLogger(__name__)


class TelegramBot:
    def __init__(
        self,
        settings: Settings,
        get_status: Callable[[], str],
        get_prices: Callable[[], str],
        get_performance: Callable[[], str],
        get_positions: Callable[[], str],
        manage_coin: Callable[[str], str],
        get_keyboard: Callable[[], dict[str, Any]],
        get_symbol_status: Callable[[str], str],
    ):
        self.settings = settings
        self.base_url = f"https://api.telegram.org/bot{settings.telegram_bot_token}"
        self.chat_id = str(settings.telegram_chat_id)
        self.get_status = get_status
        self.get_prices = get_prices
        self.get_performance = get_performance
        self.get_positions = get_positions
        self.manage_coin = manage_coin
        self.get_keyboard = get_keyboard
        self.get_symbol_status = get_symbol_status
        self.session = requests.Session()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._offset = 0
        self._awaiting: dict[str, str] = {}
        self._last_conflict_log_at = 0.0

    @property
    def enabled(self) -> bool:
        return bool(self.settings.telegram_bot_token and self.chat_id)

    def _call(self, method: str, payload: dict[str, Any]) -> Optional[dict[str, Any]]:
        if not self.enabled:
            return None
        try:
            response = self.session.post(f"{self.base_url}/{method}", json=payload, timeout=35)
            if response.status_code == 409:
                now = time.time()
                if now - self._last_conflict_log_at > 60:
                    logger.error("telegram_polling_conflict method=%s another_bot_consumer_may_be_running", method)
                    self._last_conflict_log_at = now
                return None
            response.raise_for_status()
            body = response.json()
            if not body.get("ok"):
                logger.warning("telegram_api_error method=%s description=%s", method, body.get("description"))
            return body
        except requests.RequestException as exc:
            logger.warning("telegram_request_failed method=%s error=%s", method, exc)
            return None

    def send_message(self, text: str, chat_id: Optional[str] = None, with_keyboard: bool = False) -> None:
        payload: dict[str, Any] = {"chat_id": chat_id or self.chat_id, "text": text, "disable_web_page_preview": True}
        if with_keyboard:
            payload["reply_markup"] = self.get_keyboard()
        self._call("sendMessage", payload)

    def alert(self, text: str) -> None:
        self.send_message(text, with_keyboard=True)

    def _get_updates(self) -> list[dict[str, Any]]:
        body = self._call("getUpdates", {"offset": self._offset, "timeout": 25, "allowed_updates": ["message"]})
        result = body.get("result", []) if body else []
        return result if isinstance(result, list) else []

    def _help_text(self) -> str:
        return (
            "نظام توصيات Binance Spot — تنبيهات ومتابعة افتراضية فقط دون تنفيذ.\n\n"
            "من زر إدارة العملات ورأس المال استخدم إحدى الصيغ:\n"
            "أضف <SYMBOL> <AMOUNT>\n"
            "عدّل <SYMBOL> <AMOUNT>\n"
            "احذف <SYMBOL>\n"
            "القائمة\n\n"
            "بعد الإضافة تُفتح متابعة السعر والإشارات تلقائياً عبر Binance WebSocket."
        )

    def _handle_coin_command(self, chat_id: str, text: str) -> None:
        add_or_update = re.fullmatch(r"(?:أضف|اضف|add|عدّل|عدل|تعديل|update)\s+([A-Za-z0-9_-]+)\s+([0-9]+(?:\.[0-9]+)?)", text, re.IGNORECASE)
        remove = re.fullmatch(r"(?:احذف|حذف|remove)\s+([A-Za-z0-9_-]+)", text, re.IGNORECASE)
        if text in ("القائمة", "list"):
            self._awaiting.pop(chat_id, None)
            self.send_message(self.manage_coin("list"), chat_id, with_keyboard=True)
            return
        if add_or_update:
            verb = text.split(maxsplit=1)[0].lower()
            action = "update" if verb in ("عدّل", "عدل", "تعديل", "update") else "add"
            symbol = add_or_update.group(1).upper()
            amount = float(add_or_update.group(2))
            self._awaiting.pop(chat_id, None)
            self.send_message(self.manage_coin(f"{action}:{symbol}:{amount}"), chat_id, with_keyboard=True)
            return
        if remove:
            symbol = remove.group(1).upper()
            self._awaiting.pop(chat_id, None)
            self.send_message(self.manage_coin(f"remove:{symbol}"), chat_id, with_keyboard=True)
            return
        self.send_message("صيغة غير صحيحة. استخدم: أضف <SYMBOL> <AMOUNT>", chat_id)

    def _handle_text(self, chat_id: str, text: str) -> None:
        if chat_id != self.chat_id:
            logger.warning("telegram_unauthorized_chat chat_id=%s", chat_id)
            return
        text = text.strip()
        if text in ("/start", "/help", "مساعدة"):
            self.send_message(self._help_text(), chat_id, with_keyboard=True)
            return
        if text in ("🪙 إدارة العملات ورأس المال", "🪙 إدارة العملات", "/coins", "/capital"):
            self._awaiting[chat_id] = "coin"
            self.send_message(
                "أرسل الأمر في رسالة واحدة:\n\n"
                "أضف <SYMBOL> <AMOUNT>\n"
                "عدّل <SYMBOL> <AMOUNT>\n"
                "احذف <SYMBOL>\n"
                "القائمة",
                chat_id,
            )
            return
        if text in ("📈 الأسعار الحية", "/prices"):
            self.send_message(self.get_prices(), chat_id, with_keyboard=True)
            return
        if text in ("📊 أداء النظام", "/performance"):
            self.send_message(self.get_performance(), chat_id, with_keyboard=True)
            return
        if text in ("📂 الصفقات", "/positions"):
            self.send_message(self.get_positions(), chat_id, with_keyboard=True)
            return
        if text in ("ℹ️ الحالة", "/status"):
            self.send_message(self.get_status(), chat_id, with_keyboard=True)
            return
        if text.startswith("🔎 "):
            self.send_message(self.get_symbol_status(text[2:].strip().upper()), chat_id, with_keyboard=True)
            return

        if self._awaiting.get(chat_id) == "coin":
            self._handle_coin_command(chat_id, text)
            return
        self.send_message("استخدم /start لعرض الأزرار والتعليمات.", chat_id, with_keyboard=True)

    def _handle_update(self, update: dict[str, Any]) -> None:
        self._offset = max(self._offset, int(update.get("update_id", 0)) + 1)
        message = update.get("message") or {}
        chat = message.get("chat") or {}
        text = message.get("text")
        if text is not None and chat.get("id") is not None:
            self._handle_text(str(chat["id"]), str(text))

    def _run(self) -> None:
        if not self.enabled:
            logger.warning("telegram_disabled_missing_credentials")
            return
        # A webhook and getUpdates cannot be used at the same time. This is safe
        # for this polling-based service and makes a stale webhook non-blocking.
        self._call("deleteWebhook", {"drop_pending_updates": False})
        self.send_message("تم تشغيل نظام التوصيات. أضف العملات ورأس مال كل عملة من الزر الديناميكي.", with_keyboard=True)
        while not self._stop.is_set():
            try:
                for update in self._get_updates():
                    self._handle_update(update)
            except Exception as exc:
                logger.warning("telegram_polling_error error=%s", exc)
                self._stop.wait(5)

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="telegram-polling", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)
