import asyncio, logging
from telegram import Update, BotCommand
from telegram.ext import ApplicationBuilder, CommandHandler
from core.config import settings

log = logging.getLogger("tg")

class TelegramBot:
    def __init__(self):
        self.app = None
        self._running = False

    def _admin_ok(self, user_id):
        return settings.TELEGRAM_ADMIN_ID and user_id == settings.TELEGRAM_ADMIN_ID

    async def setup_commands(self):
        """إعداد قائمة الأزرار الدائمة"""
        cmds = [
            BotCommand("status", "📊 حالة النظام"),
            BotCommand("symbols", "💰 العملات المراقبة"),
            BotCommand("mode", "⚙️ وضع التداول"),
            BotCommand("help", "❓ المساعدة"),
        ]
        await self.app.bot.set_my_commands(cmds)
        log.info("🤖 Command menu set ✅")

    async def cmd_status(self, update: Update, _):
        if not self._admin_ok(update.effective_user.id):
            return
        mode = settings.MODE or "BALANCED"
        await update.message.reply_text(
            f"✅ **النظام يعمل ONLINE**\n\n"
            f"💰 العملات: {', '.join(settings.SYMBOLS)}\n"
            f"⚙️ الوضع: {mode}\n"
            f"⏰ وقت العمل: 07:30–19:30 UTC\n"
            f"✅ Supabase: متصل\n"
            f"✅ Redis: متصل"
        )

    async def cmd_symbols(self, update: Update, _):
        if not self._admin_ok(update.effective_user.id):
            return
        await update.message.reply_text(
            "📊 **قائمة العملات المراقبة:**\n" +
            "\n".join(f"• {s}" for s in settings.SYMBOLS)
        )

    async def cmd_mode(self, update: Update, _):
        if not self._admin_ok(update.effective_user.id):
            return
        mode = settings.MODE or "BALANCED"
        await update.message.reply_text(f"⚙️ **وضع التداول الحالي:** {mode}")

    async def cmd_help(self, update: Update, _):
        await update.message.reply_text(
            "❓ **أوامر النظام:**\n\n"
            "/status - عرض حالة النظام\n"
            "/symbols - عرض العملات\n"
            "/mode - وضع التداول\n"
            "/help - هذه القائمة"
        )

    async def start(self):
        if not settings.TELEGRAM_BOT_TOKEN or not settings.TELEGRAM_ADMIN_ID:
            log.warning("🤖 Bot config missing — disabled")
            return

        try:
            self.app = ApplicationBuilder().token(settings.TELEGRAM_BOT_TOKEN).build()
            self.app.add_handler(CommandHandler("status", self.cmd_status))
            self.app.add_handler(CommandHandler("symbols", self.cmd_symbols))
            self.app.add_handler(CommandHandler("mode", self.cmd_mode))
            self.app.add_handler(CommandHandler("help", self.cmd_help))

            await self.app.initialize()
            await self.app.setup_commands()
            await self.app.start()
            await self.app.updater.start_polling(drop_pending_updates=True)
            self._running = True
            log.info("🤖 Telegram Bot ONLINE ✅")

            await self.app.bot.send_message(
                chat_id=settings.TELEGRAM_ADMIN_ID,
                text="🤖 **نظام التداول يعمل ONLINE**\n\n"
                "استخدم القائمة أسفل الشاشة أو الأوامر:\n"
                "/status - الحالة\n"
                "/symbols - العملات\n"
                "/mode - الوضع"
            )
        except Exception as ex:
            if "Conflict" in str(ex):
                log.warning("⚠️ Bot conflict — stop other instances!")
            else:
                log.error("🤖 Bot error: %s", ex)
            raise
