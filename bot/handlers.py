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
    if ADMIN_ID != 0 and user_id != ADMIN_ID:
        return False
    return True

async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_admin(update): return
    await update.message.reply_text("🤖 *نظام التداول V3*", reply_markup=get_main_menu(), parse_mode='Markdown')

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    try: await query.answer()
    except: pass

    # منطق الأزرار الـ Inline (التي تظهر داخل الرسائل)
    if data == 'main_menu':
        await query.edit_message_text("القائمة الرئيسية:", reply_markup=get_main_menu())
    elif data == 'private_trades':
        await query.edit_message_text("🌟 *مركز التحكم بالصفقات الخاصة*", reply_markup=get_private_trades_menu(), parse_mode='Markdown')
    elif data in ['elite_on', 'elite_off']:
        is_on = (data == 'elite_on')
        async with AsyncSessionLocal() as session:
            res = await session.execute(select(UserConfig).where(UserConfig.telegram_id == ADMIN_ID))
            cfg = res.scalars().first()
            if cfg: cfg.elite_enabled = is_on; await session.commit()
        await query.edit_message_text("✅ تم تحديث حالة الإشارات.", reply_markup=get_main_menu())
    elif data == 'elite_instant_report':
        # ... (نفس منطق التقرير الخاص بك)
        pass 
    elif data == 'coins':
        await query.edit_message_text("🪙 إدارة العملات:", reply_markup=get_coins_menu())
    elif data == 'add_coin':
        context.user_data["state"] = 'WAITING_COIN_NAME'
        await query.edit_message_text("✍️ أرسل رمز العملة (مثال: SOLUSDT):")

async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_admin(update): return
    text = update.message.text.strip()
    
    # --- الجسر الجديد: معالجة نصوص الأزرار السفلية ---
    if "الصفقات الخاصة" in text:
        await update.message.reply_text("🌟 مركز التحكم بالصفقات:", reply_markup=get_private_trades_menu())
    elif "الأسعار الحية" in text:
        # هنا يمكنك استدعاء كود جلب الأسعار أو التوجيه لزر الـ Inline
        await update.message.reply_text("📈 جارٍ جلب الأسعار...")
    elif "إدارة العملات" in text:
        await update.message.reply_text("🪙 قائمة العملات:", reply_markup=get_coins_menu())
    
    # --- أزرار التشغيل والإيقاف (تعمل لديك بالفعل) ---
    elif "▶️ بدء التعلم الخفي" in text:
        # (ضع منطقك هنا)
        await update.message.reply_text("🚀 تم بدء محرك التعلم.")
    elif "⏸️ إيقاف التعلم الخفي" in text:
        # (ضع منطقك هنا)
        await update.message.reply_text("⏸️ تم إيقاف محرك التعلم.")
        
    # --- معالجة الإدخال (العملات) ---
    state = context.user_data.get("state")
    if state == 'WAITING_COIN_NAME':
        context.user_data["temp_symbol"] = text.upper()
        context.user_data["state"] = 'WAITING_COIN_CAPITAL'
        await update.message.reply_text(f"💰 رأس المال لـ {text.upper()}؟")
    elif state == 'WAITING_COIN_CAPITAL':
        # (ضع كود إضافة العملة هنا كما كان سابقاً)
        pass
