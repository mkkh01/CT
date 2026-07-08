import os
import sys
import asyncio
import logging
import traceback
import time
from keep_alive import keep_alive
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ConversationHandler
from telegram.request import HTTPXRequest
from telegram.error import Conflict
from config import TELEGRAM_TOKEN, ADMIN_ID, validate_config
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
from Core.redis_client import redis_client

# تشغيل خادم Keep-Alive
keep_alive()

BOT_INSTANCE_LOCK_KEY = "ct:telegram:polling_lock"
BOT_INSTANCE_LOCK_TTL = int(os.environ.get("BOT_INSTANCE_LOCK_TTL", "300"))
BOT_INSTANCE_LOCK_REFRESH = int(os.environ.get("BOT_INSTANCE_LOCK_REFRESH", "120"))


def _instance_lock_client():
    return getattr(redis_client, "redis", None)


def acquire_bot_instance_lock(max_wait_seconds: int = 10, retry_interval: int = 2) -> bool:
    """Acquire a distributed lock so only one bot instance polls Telegram."""
    client = _instance_lock_client()
    if client is None:
        logger.warning("⚠️ [SYSTEM] Redis غير متاح؛ سيتم تشغيل البوت بدون قفل موزع.")
        return True

    token = f"{os.getenv('RENDER_SERVICE_ID', 'local')}:{os.getpid()}:{int(time.time()*1000)}"
    deadline = time.time() + max_wait_seconds
    
    # محاولة كسر القفل القديم إذا كان موجوداً ولم يتغير لفترة طويلة (فقط في حال لم يكن NX)
    # ولكن NX=True كافية عادةً. المشكلة هنا هي تضارب getUpdates الحقيقي.
    
    while True:
        try:
            # محاولة الحصول على القفل
            ok = client.set(BOT_INSTANCE_LOCK_KEY, token, nx=True, ex=BOT_INSTANCE_LOCK_TTL)
            if ok:
                app_state = {"token": token, "client": client}
                globals()["_BOT_LOCK_STATE"] = app_state
                logger.info("✅ [SYSTEM] تم الحصول على قفل البوت الموزع.")
                return True
            
            # التحقق مما إذا كان القفل الحالي هو نفسه (إعادة تشغيل سريعة)
            current = client.get(BOT_INSTANCE_LOCK_KEY)
            if current and current.startswith(f"{os.getenv('RENDER_SERVICE_ID', 'local')}:"):
                # إذا كان من نفس الخدمة، ربما تكون عملية إعادة تشغيل، سنحاول الاستيلاء عليه
                client.set(BOT_INSTANCE_LOCK_KEY, token, ex=BOT_INSTANCE_LOCK_TTL)
                app_state = {"token": token, "client": client}
                globals()["_BOT_LOCK_STATE"] = app_state
                logger.info("♻️ [SYSTEM] تم استعادة قفل البوت الموزع (إعادة تشغيل).")
                return True

        except Exception as exc:
            logger.warning(f"⚠️ [SYSTEM] تعذر إنشاء قفل البوت الموزع: {exc}")
            return True

        if time.time() >= deadline:
            logger.error("❌ [SYSTEM] يوجد مثيل آخر من البوت يعمل الآن. سيتم الإقلاع بدون polling لتجنب تضارب Telegram.")
            return False

        logger.info("⏳ [SYSTEM] انتظار تحرير قفل البوت قبل بدء polling...")
        time.sleep(retry_interval)


async def refresh_bot_instance_lock():
    state = globals().get("_BOT_LOCK_STATE")
    if not state:
        return
    client = state.get("client")
    token = state.get("token")
    while True:
        await asyncio.sleep(BOT_INSTANCE_LOCK_REFRESH)
        try:
            current = client.get(BOT_INSTANCE_LOCK_KEY)
            if current != token:
                logger.error("❌ [SYSTEM] فُقد قفل البوت الموزع؛ إيقاف التحديث الذاتي.")
                return
            client.expire(BOT_INSTANCE_LOCK_KEY, BOT_INSTANCE_LOCK_TTL)
        except Exception as exc:
            logger.warning(f"⚠️ [SYSTEM] تعذر تحديث قفل البوت الموزع: {exc}")
            return


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
    safe_create_task(refresh_bot_instance_lock(), name="RefreshBotInstanceLock")

async def error_handler(update, context):
    """سجل الأخطاء مع Traceback كامل"""
    if isinstance(context.error, Conflict):
        logger.warning("⚠️ [TELEGRAM] Conflict detected. Another instance is likely running.")
        return
    
    logger.error(msg="Exception while handling an update:", exc_info=context.error)
    tb_list = traceback.format_exception(None, context.error, context.error.__traceback__)
    tb_string = "".join(tb_list)
    print(f"❌ [TELEGRAM ERROR] {tb_string}")

def main():
    # منع تشغيل أكثر من نسخة للبوت باستخدام File Lock
    lock_file = "/tmp/bot.lock"
    try:
        import fcntl
        f = open(lock_file, 'w')
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except (ImportError, IOError):
        import socket
        try:
            lock_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            lock_socket.bind(('127.0.0.1', 47111))
        except socket.error:
            print("⚠️ [SYSTEM] هناك نسخة أخرى من البوت تعمل بالفعل (Socket Lock).")
            # على Render، قد يحدث تداخل أثناء الـ Deploy، سننتظر قليلاً بدلاً من الخروج الفوري
            time.sleep(5)
            # سنحاول مرة أخرى أو نخرج
            sys.exit(0) 
    except Exception as e:
        print(f"⚠️ [SYSTEM] هناك نسخة أخرى من البوت تعمل بالفعل (File Lock).")
        sys.exit(0)

    print("🚀 جاري إقلاع نظام التداول المؤسسي CT V4.0...")

    # Validate critical configuration before touching any external service.
    # A failing validate_config() raises RuntimeError with a clear message.
    try:
        validate_config()
    except RuntimeError as cfg_err:
        logger.critical(str(cfg_err))
        print(f"\n🚫 FATAL: {cfg_err}")
        sys.exit(1)

    loop = asyncio.get_event_loop()
    loop.run_until_complete(init_db())
    
    request_config = HTTPXRequest(connect_timeout=20, read_timeout=20)
    app = Application.builder().token(TELEGRAM_TOKEN).request(request_config).post_init(post_init).build()
    
    app.add_error_handler(error_handler)
    
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
    
    # محاولة الحصول على القفل الموزع
    if not acquire_bot_instance_lock():
        logger.error("🚫 [SYSTEM] تم منع تشغيل polling لمنع تضارب getUpdates بين مثيلين.")
        # بدلاً من الإغلاق، سنقوم بتشغيل التطبيق بدون polling للحفاظ على الـ Background Tasks إذا لزم الأمر
        # أو نخرج بسلام. في Render، الخروج بسلام (0) يمنع الـ Crash Loop
        sys.exit(0)
        
    try:
        # استخدام drop_pending_updates=True لتنظيف أي طلبات عالقة
        app.run_polling(drop_pending_updates=True, close_loop=False)
    except Conflict:
        logger.error("🚫 [TELEGRAM] Conflict detected during polling. Exiting gracefully.")
        sys.exit(0)
    except Exception as e:
        logger.error(f"❌ [SYSTEM] Unexpected error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
