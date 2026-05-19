# main.py
import os
import sys

# 1. تشغيل الخادم الوهمي فوراً في أول ثانية لإرضاء منصة Render
from keep_alive import keep_alive
keep_alive()
print("✅ تم فتح المنفذ بنجاح! جاري تحميل مكتبات الذكاء الاصطناعي الثقيلة (قد يستغرق دقيقة)...")

# 2. الآن نقوم باستيراد باقي المكتبات براحة تامة
import asyncio
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters
from config import TELEGRAM_TOKEN, ADMIN_ID
from database import init_db, AsyncSessionLocal, Watchlist
from bot.handlers import start_cmd, button_handler, text_handler
from Core.whale_tracker import WhaleTracker
from sqlalchemy import select

async def start_background_tasks(bot):
    """تشغيل المهام الخلفية وجلب العملات من قاعدة البيانات"""
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(Watchlist.symbol))
        symbols_to_track = result.scalars().all()
    
    if not symbols_to_track:
        print("⚠️ لا توجد عملات في المراقبة. سيتم مراقبة BTCUSDT افتراضياً.")
        symbols_to_track = ["BTCUSDT"]
        
    # تمرير البوت والـ ID لكي يستطيع الرادار إرسال رسائل
    tracker = WhaleTracker(bot=bot, chat_id=ADMIN_ID)
    print(f"🔄 جاري تشغيل رادار الحيتان للعملات: {symbols_to_track}")
    asyncio.create_task(tracker.start_tracking(symbols_to_track))

async def main():
    print("🚀 جاري إقلاع النظام المتقدم...")
    await init_db()
    
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    
    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))
    
    await app.initialize()
    
    # تشغيل المهام الخلفية بعد تهيئة البوت
    await start_background_tasks(app.bot)
    
    print("✅ النظام يعمل بكامل طاقته! اذهب إلى تليجرام وأرسل /start")
    
    await app.start()
    await app.updater.start_polling()
    
    while True:
        await asyncio.sleep(3600)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n🛑 تم إيقاف النظام بأمان.")
