import asyncio, logging
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
from core.config import settings

log = logging.getLogger("tg")

class TelegramBot:
    def __init__(self):
        self.app = None
        self._q = asyncio.Queue()

    def _admin(self, u):
        return settings.TELEGRAM_ADMIN_ID and u.id == settings.TELEGRAM_ADMIN_ID

    async def _cmd_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._admin(update.effective_user):
            return
        await update.message.reply_text(
            f"✅ System online\nSymbols: {', '.join(settings.SYMBOLS)}\nMode: {settings.MODE}"
        )

    async def _cmd_symbols(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._admin(update.effective_user):
            return
        await update.message.reply_text(", ".join(settings.SYMBOLS))

    async def start(self):
        if not settings.TELEGRAM_BOT_TOKEN:
            log.warning("🤖 Telegram token missing — bot disabled")
            return
        try:
            self.app = ApplicationBuilder().token(settings.TELEGRAM_BOT_TOKEN).build()
            self.app.add_handler(CommandHandler("status", self._cmd_status))
            self.app.add_handler(CommandHandler("symbols", self._cmd_symbols))
            await self.app.initialize()
            await self.app.start()
            await self.app.updater.start_polling(drop_pending_updates=True)
            log.info("🤖 Telegram bot online")
            await self.send_admin("🤖 CT Trading System online")
        except Exception as ex:
            log.error("🤖 Telegram init error: %s", ex)

    async def send_admin(self, text):
        if settings.TELEGRAM_ADMIN_ID and settings.TELEGRAM_BOT_TOKEN and self.app:
            try:
                await self._q.put(text)
            except Exception as ex:
                log.debug("tg send error: %s", ex)
