from telegram import Update
from telegram.ext import ContextTypes
from datetime import datetime
from sqlalchemy import select, desc
import httpx

from config import ADMIN_ID
from database import AsyncSessionLocal, TrackedCoin, UserConfig, PaperTrade
from bot.keyboards import get_main_menu, get_coins_menu, get_private_trades_menu

async def check_admin(update: Update) -> bool:
    user_id = update.effective_user.id
    return ADMIN_ID == 0 or user_id == ADMIN_ID

async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_admin(update): return
    await update.message.reply_text("🤖 *نظام التداول V3*", reply_markup=get_main_menu(), parse_mode='Markdown')

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    try: await query.answer()
    except: pass

    # دالة الجسر: تحذف الرسالة القديمة (التي كانت Inline) وترسل رسالة جديدة (بأزرار Reply السفلية)
    async def jump_to_main(msg):
        try: await msg.delete()
        except: pass
        await context.bot.send_message(
            chat_id=msg.chat_id,
            text="🏠 القائمة الرئيسية:",
            reply_markup=get_main_menu()
        )

    if data == 'main_menu':
        await jump_to_main(query.message)
            
    elif data == 'private_trades':
        await query.edit_message_text(
            "🌟 *مركز التحكم بالصفقات الخاصة*", 
            reply_markup=get_private_trades_menu(), 
            parse_mode='Markdown'
        )

    elif data in ['elite_on', 'elite_off']:
        is_on = (data == 'elite_on')
        async with AsyncSessionLocal() as session:
            res = await session.execute(select(UserConfig).where(UserConfig.telegram_id == ADMIN_ID))
            cfg = res.scalars().first()
            if cfg: 
                cfg.elite_enabled = is_on
                await session.commit()
        # نعود للقائمة الرئيسية (الأزرار السفلية) عبر الجسر
        await jump_to_main(query.message)

    elif data == 'elite_instant_report':
        # أضف منطق التقرير هنا
        await query.message.reply_text("📋 جاري إعداد التقرير...")

    elif data == 'coins':
        await query.edit_message_text("🪙 إدارة العملات:", reply_markup=get_coins_menu())

    elif data == 'add_coin':
        context.user_data["state"] = 'WAITING_COIN_NAME'
        await query.edit_message_text("✍️ أرسل رمز العملة (مثال: SOLUSDT):")

async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_admin(update): return
    text = update.message.text.strip()
    
    # معالجة الأزرار السفلية (ReplyKeyboard)
    if "الصفقات الخاصة" in text:
        await update.message.reply_text("🌟 مركز التحكم:", reply_markup=get_private_trades_menu())
    elif "الأسعار الحية" in text:
        await update.message.reply_text("📈 جاري جلب الأسعار...")
    elif "إدارة العملات" in text:
        await update.message.reply_text("🪙 إدارة العملات:", reply_markup=get_coins_menu())
    
    # أزرار التعلم الخفي
    elif "بدء التعلم الخفي" in text:
        await update.message.reply_text("🚀 تم بدء محرك التعلم.")
    elif "إيقاف التعلم الخفي" in text:
        await update.message.reply_text("⏸️ تم إيقاف محرك التعلم.")
        
    # منطق إضافة العملة
    state = context.user_data.get("state")
    if state == 'WAITING_COIN_NAME':
        context.user_data["temp_symbol"] = text.upper()
        context.user_data["state"] = 'WAITING_COIN_CAPITAL'
        await update.message.reply_text(f"💰 رأس المال لـ {text.upper()}؟")
    elif state == 'WAITING_COIN_CAPITAL':
        try:
            capital = float(text)
            symbol = context.user_data.get("temp_symbol")
            async with AsyncSessionLocal() as session:
                new_coin = TrackedCoin(symbol=symbol, allocated_capital=capital)
                session.add(new_coin)
                await session.commit()
            await update.message.reply_text(f"✅ تمت إضافة {symbol}.", reply_markup=get_main_menu())
            context.user_data["state"] = None
        except:
            await update.message.reply_text("⚠️ خطأ في الرقم.")
