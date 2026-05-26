from telegram import Update
from telegram.ext import (
    ContextTypes, ConversationHandler, CommandHandler,
    MessageHandler, CallbackQueryHandler, filters
)
from telegram.error import Conflict, NetworkError, TimedOut  # ⬅️ إضافة أخطاء تيليجرام
from datetime import datetime
from sqlalchemy import select
from config import ADMIN_ID
from database import AsyncSessionLocal, TrackedCoin, UserConfig
from bot.keyboards import get_main_menu, get_coins_menu, get_private_trades_menu, get_timeframe_menu

# تعريف حالات المحادثة لإضافة العملة
NAME, CAPITAL, TIMEFRAME = range(3)

async def check_admin(update: Update) -> bool:
    """التحقق من صلاحية المستخدم - تم تحسينه لمنع الدخول إذا كان المعرف غير مضبوط"""
    user_id = update.effective_user.id
    # ✅ تعديل: إذا كان ADMIN_ID صفراً، نرفض الدخول تماماً بدلاً من السماح للجميع
    return ADMIN_ID != 0 and user_id == ADMIN_ID

# ⬅️ إضافة: معالج الأخطاء العام لحل مشكلة "No error handlers"
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """معالجة جميع الأخطاء التي تحدث في البوت"""
    error = context.error
    print(f"⚠️ حدث خطأ: {str(error)}")

    # ✅ حل مشكلة Conflict تحديداً
    if isinstance(error, Conflict):
        print("🚨 كشف نسخة أخرى تعمل (Conflict). سيتم تجاهل هذا الخطأ وإعادة المحاولة...")
        return  # نكمل العمل ولا نتوقف

    # معالجة أخطاء الشبكة والاتصال (مثل مشكلة WebSocket والانقطاع)
    elif isinstance(error, (NetworkError, TimedOut)):
        print("🔌 مشكلة في الشبكة، سيتم إعادة المحاولة تلقائياً...")
        return

    # في حالات أخرى، طباعة التفاصيل للتشخيص
    if update and isinstance(update, Update) and update.effective_message:
        try:
            await update.effective_message.reply_text("❌ حدث خطأ غير متوقع، يرجى المحاولة لاحقاً.")
        except:
            pass


async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_admin(update): 
        return
    await update.message.reply_text(
        "🤖 *نظام التداول V3*", 
        reply_markup=get_main_menu(), 
        parse_mode='Markdown'
    )

# --- منطق إضافة العملة ---
async def start_add_coin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("✍️ أرسل رمز العملة (مثال: BTCUSDT):")
    return NAME

async def get_coin_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["symbol"] = update.message.text.upper().strip() # ✅ إزالة فراغات زائدة
    await update.message.reply_text("💰 أدخل رأس المال المخصص لهذه العملة:")
    return CAPITAL

async def get_capital(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        capital_value = float(update.message.text.strip())
        if capital_value <= 0: # ✅ منع إدخال قيم سالبة أو صفر
            raise ValueError("القيمة صفر")
            
        context.user_data["capital"] = capital_value
        await update.message.reply_text("⏱️ اختر الإطار الزمني:", reply_markup=get_timeframe_menu())
        return TIMEFRAME
    except:
        await update.message.reply_text("⚠️ قيمة غير صالحة! أدخل رقماً موجباً صحيحاً:")
        return CAPITAL

async def get_timeframe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    tf = query.data.replace("tf_", "")

    # ✅ تعديل مهم جداً: حفظ الإطار الزمني في قاعدة البيانات
    async with AsyncSessionLocal() as session:
        new_coin = TrackedCoin(
            symbol=context.user_data["symbol"], 
            allocated_capital=context.user_data["capital"],
            timeframe=tf  # ✅ كان مفقوداً سابقاً! تأكد من وجود هذا العمود في نموذج قاعدة البيانات
        )
        session.add(new_coin)
        await session.commit()
    
    await query.edit_message_text(f"✅ تمت إضافة **{context.user_data['symbol']}** بنجاح.\n📊 رأس المال: {context.user_data['capital']}\n⏱️ الإطار: {tf}", parse_mode='Markdown')
    await context.bot.send_message(update.effective_chat.id, "🏠 القائمة الرئيسية:", reply_markup=get_main_menu())
    
    # ✅ مسح البيانات المؤقتة لتجنب تعارض في الجلسات القادمة
    context.user_data.clear()
    return ConversationHandler.END

# --- معالج الأزرار الرئيسية ---
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    try: 
        await query.answer()
    except:
        pass

    if data == 'main_menu':
        try: 
            await query.message.delete()
        except: 
            pass
        await context.bot.send_message(update.effective_chat.id, "🏠 القائمة الرئيسية:", reply_markup=get_main_menu())
            
    elif data == 'private_trades':
        await query.edit_message_text("🌟 *مركز التحكم*", reply_markup=get_private_trades_menu(), parse_mode='Markdown')

    elif data in ['elite_on', 'elite_off']:
        is_on = (data == 'elite_on')
        async with AsyncSessionLocal() as session:
            res = await session.execute(select(UserConfig).where(UserConfig.telegram_id == ADMIN_ID))
            cfg = res.scalars().first()
            if cfg: 
                cfg.elite_enabled = is_on
                await session.commit()
                status = "مُفعل ✅" if is_on else "معطل ❌"
                try: await query.message.edit_text(f"✅ تم تحديث الحالة: الوضع النخي {status}")
                except: pass
            else:
                # ✅ إنشاء إعدادات افتراضية إذا لم تكن موجودة
                new_cfg = UserConfig(telegram_id=ADMIN_ID, elite_enabled=is_on)
                session.add(new_cfg)
                await session.commit()

    elif data == 'coins':
        await query.edit_message_text("🪙 إدارة العملات:", reply_markup=get_coins_menu())

# --- معالج النصوص والأوامر النصية ---
async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_admin(update): 
        return
        
    text = update.message.text.strip()
    if "الصفقات الخاصة" in text:
        await update.message.reply_text("🌟 مركز التحكم:", reply_markup=get_private_trades_menu())
    elif "إدارة العملات" in text:
        await update.message.reply_text("🪙 إدارة العملات:", reply_markup=get_coins_menu())
    elif "بدء التعلم" in text:
        await update.message.reply_text("🚀 تم بدء عملية التعلم والتحليل.")
    elif "إيقاف التعلم" in text:
        await update.message.reply_text("⏸️ تم إيقاف عملية التعلم مؤقتاً.")
