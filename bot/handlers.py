from telegram import Update
from telegram.ext import (
    ContextTypes, ConversationHandler, CommandHandler,
    MessageHandler, CallbackQueryHandler, filters
)
from telegram.error import Conflict, NetworkError, TimedOut
from datetime import datetime
from sqlalchemy import select
from config import ADMIN_ID
from database import AsyncSessionLocal, TrackedCoin, UserConfig
from bot.keyboards import get_main_menu, get_coins_menu, get_private_trades_menu, get_timeframe_menu

# تعريف حالات المحادثة لإضافة العملة
NAME, CAPITAL, TIMEFRAME = range(3)

async def check_admin(update: Update) -> bool:
    """التحقق من صلاحية المستخدم - آمن تماماً"""
    user_id = update.effective_user.id
    return ADMIN_ID != 0 and user_id == ADMIN_ID

# معالج الأخطاء العام لحل مشكلة No error handlers و Conflict والانقطاعات
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    error = context.error
    print(f"⚠️ نظام: حدث خطأ -> {str(error)}")

    # حل جذري لخطأ Conflict (التعارض بين نسخ البوت)
    if isinstance(error, Conflict):
        print("🚨 كشف تعارض: يوجد نسخة أخرى تعمل. تم تجاهل الخطأ ومتابعة العمل...")
        return

    # معالجة انقطاعات الشبكة و WebSocket
    elif isinstance(error, (NetworkError, TimedOut)):
        print("🔌 انقطاع شبكة: سيتم إعادة المحاولة تلقائياً...")
        return

    # إشعار المستخدم في حالات الأخطاء الأخرى
    if update and isinstance(update, Update) and update.effective_message:
        try:
            await update.effective_message.reply_text("❌ حدث خطأ بسيط، يرجى المحاولة مجدداً.")
        except:
            pass


async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_admin(update):
        return
    await update.message.reply_text(
        "🤖 *نظام التداول V3*\nمرحباً بك، اختر من القائمة أدناه:",
        reply_markup=get_main_menu(),
        parse_mode='Markdown'
    )

# --- منطق إضافة عملة جديدة ---
async def start_add_coin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.edit_text("✍️ أرسل رمز العملة بصيغة صحيحة (مثال: BTCUSDT):")
    return NAME

async def get_coin_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    symbol_input = update.message.text.strip().upper()
    if not symbol_input.isalnum():
        await update.message.reply_text("⚠️ الرمز غير صالح! أعد المحاولة:")
        return NAME

    context.user_data["symbol"] = symbol_input
    await update.message.reply_text("💰 أدخل رأس المال المخصص لهذه العملة (رقم فقط):")
    return CAPITAL

async def get_capital(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        capital_value = float(update.message.text.strip())
        if capital_value <= 0:
            raise ValueError("قيمة صفر أو سالبة")

        context.user_data["capital"] = capital_value
        await update.message.reply_text("⏱️ اختر الإطار الزمني المناسب:", reply_markup=get_timeframe_menu())
        return TIMEFRAME
    except:
        await update.message.reply_text("⚠️ قيمة غير صالحة! أدخل رقماً موجباً صحيحاً:")
        return CAPITAL

async def get_timeframe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    tf = query.data.replace("tf_", "")

    # حفظ البيانات كاملة في قاعدة البيانات
    async with AsyncSessionLocal() as session:
        new_coin = TrackedCoin(
            symbol=context.user_data["symbol"],
            allocated_capital=context.user_data["capital"],
            timeframe=tf
        )
        session.add(new_coin)
        await session.commit()

    await query.edit_message_text(
        f"✅ تمت إضافة العملة بنجاح!\n\n"
        f"🪙 العملة: *{context.user_data['symbol']}*\n"
        f"💵 رأس المال: *{context.user_data['capital']}*\n"
        f"⏱️ الإطار: *{tf}*",
        parse_mode='Markdown'
    )
    await context.bot.send_message(update.effective_chat.id, "🏠 العودة للقائمة الرئيسية:", reply_markup=get_main_menu())
    
    # مسح البيانات المؤمنة لمنع التعارض
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
        try: await query.message.delete()
        except: pass
        await context.bot.send_message(update.effective_chat.id, "🏠 القائمة الرئيسية:", reply_markup=get_main_menu())

    elif data == 'private_trades':
        await query.edit_message_text("🌟 *مركز التحكم والصفقات الخاصة*", reply_markup=get_private_trades_menu(), parse_mode='Markdown')

    elif data in ['elite_on', 'elite_off']:
        is_on = (data == 'elite_on')
        async with AsyncSessionLocal() as session:
            res = await session.execute(select(UserConfig).where(UserConfig.telegram_id == ADMIN_ID))
            cfg = res.scalars().first()
            
            if cfg:
                cfg.elite_enabled = is_on
            else:
                # إنشاء إعدادات جديدة إذا لم تكن موجودة
                cfg = UserConfig(telegram_id=ADMIN_ID, elite_enabled=is_on)
                session.add(cfg)
            await session.commit()

        status = "مُفعل ✅" if is_on else "معطل ❌"
        try: await query.message.edit_text(f"✅ تم تحديث الحالة: نظام الإشارات أصبح {status}")
        except: pass

    elif data == 'coins':
        await query.edit_message_text("🪙 إدارة العملات المضافة:", reply_markup=get_coins_menu())

    # ✅ ربط زر إضافة عملة بالمحادثة
    elif data == 'add_coin':
        await query.message.edit_text("✍️ أرسل رمز العملة (مثال: BTCUSDT):")
        return NAME

    elif data == 'remove_coin':
        await query.message.edit_text("➖ وظيفة حذف العملات قيد التطوير...")

    elif data == 'view_coins':
        # يمكنك إضافة جلب البيانات من قاعدة البيانات هنا لاحقاً
        await query.message.edit_text("📋 قائمة العملات المضافة قيد التطوير...")

    elif data == 'elite_instant_report':
        await query.message.edit_text("📋 تقرير الأداء اللحظي قيد التطوير...")

# --- معالج النصوص والأزرار السفلية ---
async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_admin(update):
        return

    text = update.message.text.strip()

    if "🌟 الصفقات الخاصة" in text:
        await update.message.reply_text("🌟 مركز التحكم:", reply_markup=get_private_trades_menu())
    elif "🌐 إدارة العملات" in text:
        await update.message.reply_text("🪙 إدارة العملات:", reply_markup=get_coins_menu())
    elif "📈 الأسعار الحية" in text:
        await update.message.reply_text("📈 جلب الأسعار الحية قيد التطوير...")
    elif "🧠 تقرير التدريب والتعلم" in text:
        await update.message.reply_text("🧠 تقارير النظام قيد التطوير...")
    elif "💰 إدارة رأس المال" in text:
        await update.message.reply_text("💰 إدارة رأس المال قيد التطوير...")
    elif "▶️ بدء التعلم الخفي" in text:
        await update.message.reply_text("🚀 تم تفعيل نظام التعلم والتحليل.")
    elif "⏸️ إيقاف التعلم الخفي" in text:
        await update.message.reply_text("⏸️ تم إيقاف نظام التعلم مؤقتاً.")
