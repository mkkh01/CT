from __future__ import annotations

import logging
import re
import threading
from typing import Any, Callable, Optional

import requests

from .config import Settings

logger = logging.getLogger(__name__)

MAIN_KEYBOARD = {
    "keyboard": [
        [{"text": "➕ إضافة رأس مال"}, {"text": "🪙 إدارة العملات"}],
        [{"text": "📈 الأسعار الحية"}, {"text": "📊 أداء النظام"}],
        [{"text": "📂 الصفقات"}, {"text": "ℹ️ الحالة"}],
    ],
    "resize_keyboard": True,
    "is_persistent": True,
}


class TelegramBot:
    def __init__(
        self,
        settings: Settings,
        get_status: Callable[[], str],
        get_prices: Callable[[], str],
        get_performance: Callable[[], str],
        get_positions: Callable[[], str],
        set_capital: Callable[[str, float], str],
        manage_symbol: Callable[[str], str],
    ):
        self.settings = settings
        self.base_url = f"https://api.telegram.org/bot{settings.telegram_bot_token}"
        self.chat_id = str(settings.telegram_chat_id)
        self.get_status = get_status
        self.get_prices = get_prices
        self.get_performance = get_performance
        self.get_positions = get_positions
        self.set_capital = set_capital
        self.manage_symbol = manage_symbol
        self.session = requests.Session()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._offset = 0
        self._awaiting: dict[str, str] = {}

    @property
    def enabled(self) -> bool:
        return bool(self.settings.telegram_bot_token and self.chat_id)

    def _call(self, method: str, payload: dict[str, Any]) -> Optional[dict[str, Any]]:
        if not self.enabled:
            return None
        try:
            response = self.session.post(f"{self.base_url}/{method}", json=payload, timeout=35)
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
            payload["reply_markup"] = MAIN_KEYBOARD
        self._call("sendMessage", payload)

    def alert(self, text: str) -> None:
        self.send_message(text, with_keyboard=False)

    def _get_updates(self) -> list[dict[str, Any]]:
        body = self._call("getUpdates", {"offset": self._offset, "timeout": 25, "allowed_updates": ["message"]})
        result = body.get("result", []) if body else []
        return result if isinstance(result, list) else []

    def _help_text(self) -> str:
        return (
            "نظام توصيات Binance Spot — تنبيهات فقط دون تنفيذ صفقات.\n\n"
            "استخدم الأزرار لإضافة رأس المال لكل عملة، إدارة الأزواج، وعرض الأسعار والأداء والصفقات.\n"
            "تنسيق رأس المال: BTCUSDT 50\n"
            "إدارة العملات: أضف BTCUSDT أو احذف BTCUSDT"
        )

    def _handle_text(self, chat_id: str, text: str) -> None:
        if chat_id != self.chat_id:
            logger.warning("telegram_unauthorized_chat chat_id=%s", chat_id)
            return
        text = text.strip()
        if text in ("/start", "/help", "مساعدة"):
            self.send_message(self._help_text(), chat_id, with_keyboard=True)
            return
        if text in ("➕ إضافة رأس مال", "/capital"):
            self._awaiting[chat_id] = "capital"
            self.send_message("أرسل: SYMBOL AMOUNT\nمثال: BTCUSDT 50", chat_id)
            return
        if text in ("🪙 إدارة العملات", "/symbols"):
            self._awaiting[chat_id] = "symbol"
            self.send_message("أرسل: أضف BTCUSDT أو احذف BTCUSDT", chat_id)
            return
        if text in ("📈 الأسعار الحية", "/prices"):
            self.send_message(self.get_prices(), chat_id)
            return
        if text in ("📊 أداء النظام", "/performance"):
            self.send_message(self.get_performance(), chat_id)
            return
        if text in ("📂 الصفقات", "/positions"):
            self.send_message(self.get_positions(), chat_id)
            return
        if text in ("ℹ️ الحالة", "/status"):
            self.send_message(self.get_status(), chat_id, with_keyboard=True)
            return

        mode = self._awaiting.get(chat_id)
        if mode == "capital":
            match = re.fullmatch(r"([A-Za-z0-9_-]+)\s+([0-9]+(?:\.[0-9]+)?)", text)
            if not match:
                self.send_message("صيغة غير صحيحة. أرسل مثلاً: BTCUSDT 50", chat_id)
                return
            symbol, amount = match.group(1).upper(), float(match.group(2))
            self._awaiting.pop(chat_id, None)
            self.send_message(self.set_capital(symbol, amount), chat_id, with_keyboard=True)
            return
        if mode == "symbol":
            match = re.fullmatch(r"(أضف|احذف|add|remove)\s+([A-Za-z0-9_-]+)", text, re.IGNORECASE)
            if not match:
                self.send_message("صيغة غير صحيحة. أرسل: أضف BTCUSDT أو احذف BTCUSDT", chat_id)
                return
            action = "add" if match.group(1).lower() in ("أضف", "add") else "remove"
            symbol = match.group(2).upper()
            self._awaiting.pop(chat_id, None)
            self.send_message(self.manage_symbol(f"{action}:{symbol}"), chat_id, with_keyboard=True)
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
        self.send_message("تم تشغيل نظام التوصيات. لا توجد أوامر تداول متصلة بهذا البوت.", with_keyboard=True)
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
