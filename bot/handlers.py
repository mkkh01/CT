from telegram import Update
from telegram.ext import ContextTypes, ConversationHandler, CommandHandler, MessageHandler, CallbackQueryHandler, filters
from datetime import datetime
from sqlalchemy import select
from config import ADMIN_ID
from database import AsyncSessionLocal, TrackedCoin, UserConfig
from bot.keyboards import get_main_menu, get_coins_menu, get_private_trades_menu, get_timeframe_menu

# تعريف حالات المحادثة لإضافة العملة
NAME, CAPITAL, TIMEFRAME = range(3)

async def check_admin(update: Update) -> bool:
    user_id = update.effective_user.id
    return ADMIN_ID == 0 or user_id == ADMIN_ID

async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_admin(update): return
    await update.message.reply_text("🤖 *نظام التداول V3*", reply_markup=get_main_menu(), parse_mode='Markdown')

# --- Conversation Handler Logic ---
async def start_add_coin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("✍️ أرسل رمز العملة (مثال: BTCUSDT):")
    return NAME

async def get_coin_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["symbol"] = update.message.text.upper()
    await update.message.reply_text("💰 أدخل رأس المال المخصص لهذه العملة:")
    return CAPITAL

async def get_capital(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        context.user_data["capital"] = float(update.message.text)
        await update.message.reply_text("⏱️ اختر الإطار الزمني:", reply_markup=get_timeframe_menu())
        return TIMEFRAME
    except:
        await update.message.reply_text("⚠️ خطأ في الرقم، أعد المحاولة:")
        return CAPITAL

async def get_timeframe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    tf = query.data.replace("tf_", "")
    
    # حفظ في قاعدة البيانات
    async with AsyncSessionLocal() as session:
        new_coin = TrackedCoin(symbol=context.user_data["symbol"], allocated_capital=context.user_data["capital"])
        session.add(new_coin)
        await session.commit()
    
    await query.edit_message_text(f"✅ تمت إضافة {context.user_data['symbol']} بإطار {tf}.")
    await context.bot.send_message(update.effective_chat.id, "🏠 القائمة الرئيسية:", reply_markup=get_main_menu())
    return ConversationHandler.END

# --- Handler الأساسي للأزرار ---
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    try: await query.answer()
    except: pass

    if data == 'main_menu':
        try: await query.message.delete()
        except: pass
        await context.bot.send_message(update.effective_chat.id, "🏠 القائمة الرئيسية:", reply_markup=get_main_menu())
            
    elif data == 'private_trades':
        await query.edit_message_text("🌟 *مركز التحكم*", reply_markup=get_private_trades_menu(), parse_mode='Markdown')

    elif data in ['elite_on', 'elite_off']:
        is_on = (data == 'elite_on')
        async with AsyncSessionLocal() as session:
            res = await session.execute(select(UserConfig).where(UserConfig.telegram_id == ADMIN_ID))
            cfg = res.scalars().first()
            if cfg: cfg.elite_enabled = is_on; await session.commit()
        try: await query.message.delete()
        except: pass
        await context.bot.send_message(update.effective_chat.id, "✅ تم التحديث.", reply_markup=get_main_menu())

    elif data == 'coins':
        await query.edit_message_text("🪙 إدارة العملات:", reply_markup=get_coins_menu())

# --- Handler للنصوص ---
async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_admin(update): return
    text = update.message.text
    if "الصفقات الخاصة" in text:
        await update.message.reply_text("🌟 مركز التحكم:", reply_markup=get_private_trades_menu())
    elif "إدارة العملات" in text:
        await update.message.reply_text("🪙 إدارة:", reply_markup=get_coins_menu())
    elif "بدء التعلم" in text:
        await update.message.reply_text("🚀 تم البدء.")
    elif "إيقاف التعلم" in text:
        await update.message.reply_text("⏸️ تم الإيقاف.")
