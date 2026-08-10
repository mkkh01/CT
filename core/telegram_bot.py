import asyncio, logging
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler
from core.config import settings

log = logging.getLogger("tg")

class TelegramBot:
    def __init__(self):
        self.app = None
        self._running = False

    def _admin_ok(self, user_id):
        return settings.TELEGRAM_ADMIN_ID and user_id == settings.TELEGRAM_ADMIN_ID

    async def cmd_status(self, update: Update, _):
        if not self._admin_ok(update.effective_user.id):
            return
        await update.message.reply_text(
            f"✅ System ONLINE\n\n"
            f"Symbols: {', '.join(settings.SYMBOLS)}\n"
            f"Mode: {settings.MODE}\n"
            f"Time: 07:30–19:30 UTC"
        )

    async def cmd_symbols(self, update: Update, _):
        if not self._admin_ok(update.effective_user.id):
            return
        await update.message.reply_text("📊 Watchlist:\n" + "\n".join(f"• {s}" for s in settings.SYMBOLS))

    async def start(self):
        if not settings.TELEGRAM_BOT_TOKEN:
            log.warning("🤖 No bot token — bot disabled")
            return
        if not settings.TELEGRAM_ADMIN_ID:
            log.warning("🤖 No admin ID — bot disabled")
            return

        try:
            self.app = ApplicationBuilder().token(settings.TELEGRAM_BOT_TOKEN).build()
            self.app.add_handler(CommandHandler("status", self.cmd_status))
            self.app.add_handler(CommandHandler("symbols", self.cmd_symbols))

            await self.app.initialize()
            await self.app.start()
            await self.app.updater.start_polling(drop_pending_updates=True)
            self._running = True
            log.info("🤖 Telegram bot ONLINE — /status /symbols")

            if settings.TELEGRAM_ADMIN_ID:
                await self.app.bot.send_message(
                    chat_id=settings.TELEGRAM_ADMIN_ID,
                    text="🤖 CT Trading System ONLINE\nUse /status"
                )
        except Exception as ex:
            err = str(ex)
            if "Conflict" in err:
                log.warning("⚠️ Bot CONFLICT: stop any other bot instance first!")
            else:
                log.error("🤖 Bot failed: %s", err)
            raise

    async def send_admin(self, text):
        if not self._running or not settings.TELEGRAM_ADMIN_ID or not self.app:
            return
        try:
            await self.app.bot.send_message(
                chat_id=settings.TELEGRAM_ADMIN_ID,
                text=text,
                disable_web_page_preview=True
            )
        except Exception as e:
            log.debug("Send failed: %s", e)
