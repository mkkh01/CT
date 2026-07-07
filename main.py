import os
import sys
import asyncio
import logging
import traceback
from keep_alive import keep_alive
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ConversationHandler
from telegram.request import HTTPXRequest
from config import TELEGRAM_TOKEN, ADMIN_ID
from database import init_db, AsyncSessionLocal, UserConfig

# إعداد الـ Logging العام
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)
from bot.handlers import (
    start, handle_message, process_add_symbol, process_add_capital, 
    process_add_risk, process_add_tf,
    ADD_SYMBOL, ADD_CAPITAL, ADD_RISK, ADD_TF
)
from Core.trade_monitor import TradeMonitor

# تشغيل خادم Keep-Alive
keep_alive()

async def start_background_tasks(app):
    """تشغيل الرادار المؤسسي والمراقبة"""
    print("📡 [SYSTEM] جاري إطلاق الرادار المؤسسي والمراقبة اللحظية...")
    await asyncio.sleep(2)
    from Core.utils import safe_create_task
    monitor = TradeMonitor(bot=app.bot)
    safe_create_task(monitor.check_prices(), name="TradeMonitor_CheckPrices")
    print("✅ [SYSTEM] تم إطلاق الرادار المؤسسي بنجاح.")

async def post_init(app: Application):
    from Core.utils import safe_create_task
    safe_create_task(start_background_tasks(app), name="StartBackgroundTasks")

async def error_handler(update, context):
    """سجل الأخطاء مع Traceback كامل"""
    logger.error(msg="Exception while handling an update:", exc_info=context.error)
    tb_list = traceback.format_exception(None, context.error, context.error.__traceback__)
    tb_string = "".join(tb_list)
    print(f"❌ [TELEGRAM ERROR] {tb_string}")

def main():
    # منع تشغيل أكثر من نسخة للبوت باستخدام File Lock (أكثر موثوقية في بيئات الـ Containers)
    lock_file = "/tmp/bot.lock"
    try:
        import fcntl
        f = open(lock_file, 'w')
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except (ImportError, IOError):
        # Fallback to socket if fcntl is not available (e.g. Windows)
        import socket
        try:
            lock_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            lock_socket.bind(('127.0.0.1', 47111))
        except socket.error:
            print("⚠️ [SYSTEM] هناك نسخة أخرى من البوت تعمل بالفعل (Socket Lock). إغلاق النسخة الحالية.")
            sys.exit(1)
    except Exception as e:
        print(f"⚠️ [SYSTEM] هناك نسخة أخرى من البوت تعمل بالفعل (File Lock).")
        sys.exit(1)

    print("🚀 جاري إقلاع نظام التداول المؤسسي CT V4.0...")
    loop = asyncio.get_event_loop()
    loop.run_until_complete(init_db())
    
    # إعداد الطلب مع زيادة مهلة الاتصال لتجنب أخطاء الشبكة على Render
    request_config = HTTPXRequest(connect_timeout=20, read_timeout=20)
    app = Application.builder().token(TELEGRAM_TOKEN).request(request_config).post_init(post_init).build()
    
    # إضافة Error Handler
    app.add_error_handler(error_handler)
    
    # إعداد المحادثة المؤسسية لإضافة عملة
    conv_handler = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^➕ إضافة عملة$"), handle_message)],
        states={
            ADD_SYMBOL: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_add_symbol)],
            ADD_CAPITAL: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_add_capital)],
            ADD_RISK: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_add_risk)],
            ADD_TF: [CallbackQueryHandler(process_add_tf, pattern='^tf_')],
        },
        fallbacks=[CommandHandler('start', start)],
        per_message=False
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(conv_handler)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    print("✅ النظام المؤسسي جاهز بالكامل.")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
