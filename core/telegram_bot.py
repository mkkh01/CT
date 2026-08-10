import asyncio, logging
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandBase, ContextTypes, CommandHandler
from core.config import settings

log = logging.getLogger("tg")

class TelegramBot:
    def __init__(self):
        self.app = None
        self._q = asyncio.Queue()

    def _admin(self, u): return settings.TELEGRAM_ADMIN_ID and u.id==settings.TELEGRAM_ADMIN_ID

    async def _cmd_status(self, u,c):
        if not self._admin(u.effective_user): return
        await u.message.reply_text(f"✅ System online\nSymbols: {', '.join(settings.SYMBOLS)}\nMode: {settings.MODE}")

    async def _cmd_symbols(self, u,c):
        if not self._admin(u.effective_user): return
        await u.message.reply_text(", ".join(settings.SYMBOLS))

    async def start(self):
        if not settings.TELEGRAM_BOT_TOKEN:
            log.warning("🤖 Telegram token missing — bot disabled")
            return
        self.app = ApplicationBuilder().token(settings.TELEGRAM_BOT_TOKEN).build()
        self.app.add_handler(CommandHandler("status", self._cmd_status))
        self.app.add_handler(CommandHandler("symbols", self._cmd_symbols))
        await self.app.initialize()
        await self.app.start()
        await self.app.updater.start_polling(drop_pending_updates=True)
        log.info("🤖 Telegram bot online")
        await self.send_admin("🤖 CT Trading System online")
        while True:
            try:
                m = await asyncio.wait_for(self._q.get(), timeout=1)
                await self.app.bot.send_message(chat_id=settings.TELEGRAM_ADMIN_ID, text=m, parse_mode="HTML", disable_web_page_preview=True)
            except asyncio.TimeoutError: pass
            except Exception as ex: log.debug("tg send err %s",ex)

    async def send_admin(self, text):
        if settings.TELEGRAM_ADMIN_ID and settings.TELEGRAM_BOT_TOKEN:
            await self._q.put(text)
