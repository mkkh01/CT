import os
import sys
import asyncio
from keep_alive import keep_alive

# تشغيل الخادم الوهمي فوراً لضمان استمرار السيرفر على Render
keep_alive()
print("✅ خادم Keep-Alive يعمل.")

from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters
from config import TELEGRAM_TOKEN, ADMIN_ID
from database import init_db, AsyncSessionLocal, TrackedCoin
from bot.handlers import start_cmd, button_handler, text_handler
from Core.whale_tracker import WhaleTracker
from Core.trade_monitor import TradeMonitor
from sqlalchemy import select

async def start_background_tasks(app):
    """تشغيل المهام الخلفية بنظام التدرج الزمني الفائق"""
    try:
        # 1. فترة سماح طويلة (45 ثانية) عند الإقلاع للسماح لـ Render و Binance بتهدئة الاتصالات
        print("⏳ نظام الحماية: انتظار 45 ثانية قبل بدء الربط مع Binance...")
        await asyncio.sleep(45)
        
        async with AsyncSessionLocal() as session:
            result = await session.execute(select(TrackedCoin.symbol))
            symbols = result.scalars().all()
        
        if not symbols:
            symbols = ["BTCUSDT", "ETHUSDT", "XRPUSDT"]
            
        print(f"🛠️ جاري تهيئة الرادار لـ {len(symbols)} عملة...")

        # 2. رادار الحيتان (Whale Tracker)
        tracker = WhaleTracker(bot=app.bot, chat_id=ADMIN_ID)
        asyncio.create_task(tracker.start_tracking(symbols))
        
        # 3. فاصل زمني كبير (60 ثانية) بين الرادار ومراقب الصفقات
        # هذا يمنع تجاوز حد الطلبات (Rate Limit) ويحافظ على استجابة الأزرار
        await asyncio.sleep(60)
        
        # 4. مراقب الصفقات (التعلم الذاتي)
        monitor = TradeMonitor(bot=app.bot)
        asyncio.create_task(monitor.check_prices())
        
        print(f"🔄 المهام الخلفية تعمل الآن بنظام الاستقرار الفائق.")
    except Exception as e:
        print(f"⚠️ فشل بدء المهام الخلفية: {e}")

async def post_init(app: Application):
    """تُستدعى تلقائياً لتشغيل المهام الخلفية دون عرقلة البوت"""
    # استخدام create_task هنا يضمن أن البوت يبدأ استقبال الأزرار فوراً
    # بينما المهام الثقيلة تبدأ في الخلفية بعد فترة السماح
    asyncio.create_task(start_background_tasks(app))

def main():
    print("🚀 جاري إقلاع النظام المطور V3 (Stability Mode)...")
    
    # تهيئة قاعدة البيانات
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(init_db())
    except Exception as e:
        print(f"❌ خطأ في قاعدة البيانات: {e}")
    
    # بناء التطبيق
    # تم إضافة تدرج في الطلبات لضمان استجابة سريعة للأزرار
    app = Application.builder().token(TELEGRAM_TOKEN).post_init(post_init).build()
    
    # إضافة المعالجات (Handlers)
    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))
    
    print("✅ النظام V3 جاهز تماماً. الأزرار ستعمل فوراً، والتحليل سيبدأ بعد دقيقة.")
    
    # drop_pending_updates تمنع تراكم الرسائل القديمة التي تعطل البوت
    app.run_polling(drop_pending_updates=True, close_loop=False)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n🛑 تم إيقاف النظام.")
    except Exception as e:
        print(f"💥 خطأ تشغيل: {e}")
