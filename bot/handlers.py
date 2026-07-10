from telegram import Update
from telegram.ext import ContextTypes
from loguru import logger
from Core.telegram_manager import get_telegram_manager

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tm = get_telegram_manager()
    await update.message.reply_text(
        "Welcome to CT Trading Bot! 🤖\nSelect an option:",
        reply_markup=tm.get_main_keyboard()
    )

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    
    if data == 'status':
        await query.edit_message_text("System Status: Running 🟢")
    elif data == 'trades':
        await query.edit_message_text("No active trades at the moment.")
    elif data == 'settings':
        await query.edit_message_text("Settings: Live Mode=False, Signal Mode=True")
    elif data == 'performance':
        await query.edit_message_text("Performance: +5.2% this month 📈")
    elif data == 'start_bot':
        await query.edit_message_text("Bot started! ▶️")
    elif data == 'stop_bot':
        await query.edit_message_text("Bot stopped! ⏹️")

def setup_handlers(app):
    from telegram.ext import CommandHandler, CallbackQueryHandler
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(handle_callback))
