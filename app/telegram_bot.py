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
        get_coins: Callable[[], str],
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
        self.get_coins = get_coins
        self.manage_coin = manage_coin
        self.get_keyboard = get_keyboard
        self.get_symbol_status = get_symbol_status
        self.session = requests.Session()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._offset = 0
        self._awaiting: dict[str, str] = {}
        self._pending_symbol: dict[str, str] = {}
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
            "لإضافة عملة اضغط زر «إضافة عملة» ثم أرسل رمز الزوج كاملاً، وبعدها أرسل رأس المال المخصص له كرقم فقط.\n"
            "مثال الصيغة العامة: <SYMBOL> ثم <AMOUNT>\n\n"
            "يمكنك أيضاً استخدام: عدّل <SYMBOL> <AMOUNT>، احذف <SYMBOL>، القائمة، أو إلغاء."
        )

    @staticmethod
    def _normalise_symbol(text: str) -> str:
        return re.sub(r"[^A-Z0-9]", "", text.upper())

    def _clear_pending(self, chat_id: str) -> None:
        self._awaiting.pop(chat_id, None)
        self._pending_symbol.pop(chat_id, None)

    def _start_add_coin(self, chat_id: str) -> None:
        self._pending_symbol.pop(chat_id, None)
        self._awaiting[chat_id] = "symbol"
        self.send_message(
            "أرسل رمز زوج التداول الذي تريد إضافته فقط.\n"
            "اكتب الزوج كاملاً كما يظهر في Binance، ثم سأطلب رأس المال المخصص له.\n\n"
            "للإلغاء أرسل: إلغاء",
            chat_id,
        )

    def _handle_coin_command(self, chat_id: str, text: str) -> None:
        add_or_update = re.fullmatch(r"(?:أضف|اضف|add|عدّل|عدل|تعديل|update)\s+([A-Za-z0-9_-]+)\s+([0-9]+(?:\.[0-9]+)?)", text, re.IGNORECASE)
        remove = re.fullmatch(r"(?:احذف|حذف|remove)\s+([A-Za-z0-9_-]+)", text, re.IGNORECASE)
        if text in ("القائمة", "list"):
            self._clear_pending(chat_id)
            self.send_message(self.get_coins(), chat_id, with_keyboard=True)
            return
        if add_or_update:
            verb = text.split(maxsplit=1)[0].lower()
            action = "update" if verb in ("عدّل", "عدل", "تعديل", "update") else "add"
            symbol = self._normalise_symbol(add_or_update.group(1))
            amount = float(add_or_update.group(2))
            self._clear_pending(chat_id)
            self.send_message(self.manage_coin(f"{action}:{symbol}:{amount}"), chat_id, with_keyboard=True)
            return
        if remove:
            symbol = self._normalise_symbol(remove.group(1))
            self._clear_pending(chat_id)
            self.send_message(self.manage_coin(f"remove:{symbol}"), chat_id, with_keyboard=True)
            return
        self.send_message("صيغة غير صحيحة. استخدم زر إضافة عملة لإدخال الرمز ثم رأس المال في خطوتين.", chat_id)

    def _handle_pending_input(self, chat_id: str, text: str) -> bool:
        state = self._awaiting.get(chat_id)
        if state == "symbol":
            symbol = self._normalise_symbol(text)
            if not re.fullmatch(r"[A-Z0-9]{5,20}", symbol):
                self.send_message("رمز الزوج غير صالح. أرسل رمزاً كاملاً من Binance مثل <SYMBOL>USDT، أو أرسل إلغاء.", chat_id)
                return True
            self._pending_symbol[chat_id] = symbol
            self._awaiting[chat_id] = "capital"
            self.send_message(
                f"تم استلام الزوج {symbol}. الآن أرسل رأس المال المخصص له كرقم فقط بعملة USDT.\n"
                "اكتب المبلغ الذي تختاره أنت.\n\nللإلغاء أرسل: إلغاء",
                chat_id,
            )
            return True
        if state == "capital":
            try:
                amount = float(text.replace(",", "."))
            except ValueError:
                self.send_message("أرسل رأس المال كرقم موجب فقط، أو أرسل إلغاء.", chat_id)
                return True
            if amount <= 0:
                self.send_message("رأس المال يجب أن يكون أكبر من صفر. أرسل رقماً موجباً.", chat_id)
                return True
            symbol = self._pending_symbol.get(chat_id)
            if not symbol:
                self._clear_pending(chat_id)
                self.send_message("انتهت جلسة الإضافة. اضغط إضافة عملة وابدأ من جديد.", chat_id, with_keyboard=True)
                return True
            self._clear_pending(chat_id)
            self.send_message(self.manage_coin(f"add:{symbol}:{amount}"), chat_id, with_keyboard=True)
            return True
        return False

    def _handle_text(self, chat_id: str, text: str) -> None:
        if chat_id != self.chat_id:
            logger.warning("telegram_unauthorized_chat chat_id=%s", chat_id)
            return
        text = text.strip()
        if text in ("/cancel", "إلغاء", "الغاء"):
            self._clear_pending(chat_id)
            self.send_message("تم إلغاء العملية الحالية.", chat_id, with_keyboard=True)
            return
        if text in ("/start", "/help", "مساعدة"):
            self.send_message(self._help_text(), chat_id, with_keyboard=True)
            return
        if text in ("➕ إضافة عملة", "➕ إضافة العملات", "/addcoin", "إضافة"):
            self._start_add_coin(chat_id)
            return
        if text in ("🧾 العملات المضافة", "القائمة", "/list"):
            self._clear_pending(chat_id)
            self.send_message(self.get_coins(), chat_id, with_keyboard=True)
            return
        if text in ("🪙 إدارة العملات ورأس المال", "🪙 إدارة العملات", "/coins", "/capital"):
            self.send_message(self._help_text(), chat_id, with_keyboard=True)
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
        if self._handle_pending_input(chat_id, text):
            return
        if text.startswith(("أضف ", "اضف ", "add ", "عدّل ", "عدل ", "تعديل ", "update ", "احذف ", "حذف ", "remove ")):
            self._handle_coin_command(chat_id, text)
            return
        self.send_message("استخدم زر «إضافة عملة» لإدخال الزوج ثم رأس المال، أو أرسل /start.", chat_id, with_keyboard=True)

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
        # Wait a few seconds for any previous instance to release the polling lock on Render.
        time.sleep(5)
        self._call("deleteWebhook", {"drop_pending_updates": False})
        self.send_message("تم تشغيل نظام التوصيات. استخدم زر إضافة عملة لإدخال الزوج ثم رأس المال.", with_keyboard=True)
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
