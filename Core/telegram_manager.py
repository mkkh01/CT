import asyncio
from telegram import Bot, Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, ContextTypes
from loguru import logger
from config.settings import TELEGRAM_TOKEN, ADMIN_ID
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
        # Handlers will be added here or in bot/handlers.py
        await self.app.initialize()
        await self.app.start()
        await self.app.updater.start_polling()

_telegram_manager = None

def get_telegram_manager():
    global _telegram_manager
    if _telegram_manager is None:
        _telegram_manager = TelegramManager()
    return _telegram_manager

def set_telegram_manager(mgr):
    global _telegram_manager
    _telegram_manager = mgr
