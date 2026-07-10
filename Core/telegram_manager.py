import asyncio
from telegram import Bot, Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, ContextTypes
from loguru import logger
try:
    import config
    TELEGRAM_TOKEN = getattr(config, "TELEGRAM_TOKEN", None)
    ADMIN_ID = getattr(config, "ADMIN_ID", None)
    PORT = getattr(config, "PORT", 10000)
    WEBHOOK_URL = getattr(config, "WEBHOOK_URL", "")
except ImportError:
    from config.settings import TELEGRAM_TOKEN, ADMIN_ID
    PORT = 10000
    WEBHOOK_URL = ""
from config.constants import *

class TelegramManager:
    def __init__(self):
        self.token = TELEGRAM_TOKEN
        self.admin_id = ADMIN_ID
        self.app = None
        if self.token:
            self.app = ApplicationBuilder().token(self.token).build()
            logger.info("Telegram Application built.")
        else:
            logger.warning("Telegram Token missing.")

    async def send_message(self, chat_id, text, reply_markup=None):
        if not self.app: return
        try:
            await self.app.bot.send_message(chat_id=chat_id, text=text, reply_markup=reply_markup, parse_mode='Markdown')
        except Exception as e:
            logger.error(f"Telegram send_message error: {e}")

    async def send_admin(self, text):
        await self.send_message(self.admin_id, text)

    def get_main_keyboard(self):
        keyboard = [
            [InlineKeyboardButton(BUTTON_STATUS, callback_data='status'), InlineKeyboardButton(BUTTON_TRADES, callback_data='trades')],
            [InlineKeyboardButton(BUTTON_SETTINGS, callback_data='settings'), InlineKeyboardButton(BUTTON_PERFORMANCE, callback_data='performance')],
            [InlineKeyboardButton(BUTTON_START, callback_data='start_bot'), InlineKeyboardButton(BUTTON_STOP, callback_data='stop_bot')]
        ]
        return InlineKeyboardMarkup(keyboard)

    async def start_polling(self):
        if not self.app: return
        logger.info("Starting Telegram bot polling...")
        await self.app.initialize()
        await self.app.start()
        await self.app.updater.start_polling()

    async def start_webhook(self):
        if not self.app: return
        logger.info(f"Starting Telegram bot webhook on port {PORT}...")
        await self.app.initialize()
        await self.app.start()
        await self.app.updater.start_webhook(
            listen="0.0.0.0",
            port=PORT,
            webhook_url=f"{WEBHOOK_URL}/{self.token}"
        )
        logger.info(f"Webhook set to {WEBHOOK_URL}/{self.token}")

_telegram_manager = None

def get_telegram_manager():
    global _telegram_manager
    if _telegram_manager is None:
        _telegram_manager = TelegramManager()
    return _telegram_manager

def set_telegram_manager(mgr):
    global _telegram_manager
    _telegram_manager = mgr
