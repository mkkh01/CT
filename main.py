import os
import sys
import asyncio
from keep_alive import keep_alive

# تشغيل الخادم الوهمي
keep_alive()
print("✅ خادم Keep-Alive يعمل.")

from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ConversationHandler
from config import TELEGRAM_TOKEN, ADMIN_ID
from database import init_db, AsyncSessionLocal, TrackedCoin, UserConfig
# ✅ أضفنا استيراد error_handler هنا
from bot.handlers import (
    start_cmd, button_handler, text_handler, 
    start_add_coin, get_coin_name, get_capital, get_timeframe, 
    NAME, CAPITAL, TIMEFRAME, error_handler
)
from Core.whale_tracker import WhaleTracker
from Core.trade_monitor import TradeMonitor
from sqlalchemy import select

# --- [إضافة المحرك الجديد] ---
conv_handler = ConversationHandler(
    entry_points=[CallbackQueryHandler(start_add_coin, pattern='^add_coin$')],
    states={
        NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_coin_name)],
        CAPITAL: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_capital)],
        TIMEFRAME: [CallbackQueryHandler(get_timeframe, pattern='^tf_')]
    },
    fallbacks=[CommandHandler('cancel', lambda u, c: ConversationHandler.END)],
    # ✅ إعدادات إضافية لزيادة الاستقرار
    allow_reentry=True,
    per_message=False # ✅ إضافة لحل تحذير per_message
)

async def start_background_tasks(app):
    """تشغيل المهام الخلفية: الرادار والمراقبة بشكل متوازٍ"""
    await asyncio.sleep(5)
    tracker = WhaleTracker(bot=app.bot, chat_id=ADMIN_ID)
    monitor = TradeMonitor(bot=app.bot)
    
    # تشغيل المراقبة والرادار كمهام منفصلة لضمان عدم توقف إحداهما للأخرى
    asyncio.create_task(monitor.check_prices())
    print(f"📡 [SYSTEM] تم إطلاق مهمة مراقبة الأسعار والصفقات.")

    while True:
        try:
            async with AsyncSessionLocal() as session:
                res = await session.execute(select(UserConfig).where(UserConfig.telegram_id == ADMIN_ID))
                cfg = res.scalars().first()
                
                if cfg and cfg.elite_enabled: 
                    coin_res = await session.execute(select(TrackedCoin.symbol))
                    symbols = coin_res.scalars().all()
                    if symbols and hasattr(tracker, 'start_tracking'): 
                        await tracker.start_tracking(symbols)
                        
            await asyncio.sleep(60)
        except Exception as e:
            print(f"⚠️ [SYSTEM] خطأ في تحديث الرادار: {str(e)}")
            await asyncio.sleep(30)

async def post_init(app: Application):
    """يتم تنفيذه مرة واحدة عند بدء التشغيل"""
    asyncio.create_task(start_background_tasks(app))

def main():
    print("🚀 جاري إقلاع النظام المطور V3...")
    loop = asyncio.get_event_loop()
    try:
        loop.run_until_complete(init_db())
        print("✅ قاعدة البيانات جاهزة.")
    except Exception as e:
        print(f"❌ خطأ في قاعدة البيانات: {e}")
        return # إيقاف التشغيل إذا فشلت قاعدة البيانات

    # بناء التطبيق
    app = Application.builder().token(TELEGRAM_TOKEN).post_init(post_init).build()
    
    # ✅ خطوة أساسية لحذف أي اتصالات سابقة ومنع خطأ Conflict
    loop.run_until_complete(app.bot.delete_webhook(drop_pending_updates=True))
    
    # --- تسجيل المعالجات (الترتيب مهم جداً) ---
    app.add_handler(conv_handler)                  # 1. نظام إضافة العملات
    app.add_handler(CommandHandler("start", start_cmd)) # 2. أمر البدء
    app.add_handler(CallbackQueryHandler(button_handler)) # 3. جميع الأزرار
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler)) # 4. النصوص والقوائم
    
    # ✅ إضافة معالج الأخطاء هنا لحل المشاكل نهائياً
    app.add_error_handler(error_handler)

    print("✅ النظام جاهز بالكامل. جميع الوحدات مفعلة.")
    
    # ✅ تشغيل البوت بالإعدادات الصحيحة والمتوافقة مع الإصدار الجديد
    app.run_polling(
        drop_pending_updates=True,
        poll_interval=1.0,       # فترة جلب التحديثات (ثانية واحدة)
        timeout=10,              # ✅ تم دمج المهلة في هذا المعامل (حذفنا read_timeout و connect_timeout)
        allowed_updates=["message", "callback_query"] # ✅ تحديد أنواع التحديثات لزيادة الكفاءة
    )

if __name__ == "__main__":
    main()
