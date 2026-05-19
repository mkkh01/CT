# main.py
import asyncio
from telegram.ext import Application, CommandHandler, CallbackQueryHandler
from config import TELEGRAM_TOKEN
from database import init_db
from bot.handlers import start_cmd, button_handler

async def main():
    print("🔄 جاري تشغيل النظام...")
    
    # 1. تهيئة قاعدة البيانات (PostgreSQL)
    await init_db()
    
    # 2. تهيئة بوت التليجرام
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    
    # ربط الأوامر
    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CallbackQueryHandler(button_handler))
    
    # 3. تشغيل البوت
    print("✅ البوت يعمل الآن! اذهب إلى تليجرام وأرسل /start")
    await app.initialize()
    await app.start()
    await app.updater.start_polling()
    
    # إبقاء النظام يعمل إلى الأبد
    while True:
        await asyncio.sleep(3600)

if __name__ == "__main__":
    # تشغيل الحلقة الرئيسية
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n🛑 تم إيقاف النظام.")

