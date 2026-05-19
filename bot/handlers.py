# bot/handlers.py
from telegram import Update
from telegram.ext import ContextTypes
from bot.keyboards import get_main_menu, get_coins_menu
from config import ADMIN_ID
from database import AsyncSessionLocal, Watchlist
from sqlalchemy import select

async def check_admin(update: Update) -> bool:
    """حماية النظام: التأكد من أن المتحدث هو الأدمن"""
    user_id = update.effective_user.id
    if ADMIN_ID != 0 and user_id != ADMIN_ID:
        if update.message:
            await update.message.reply_text("⛔ عذراً، أنت غير مصرح لك.")
        return False
    return True

async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """الرد على أمر /start"""
    if not await check_admin(update): return
    
    # تصفير أي حالة سابقة
    context.user_data['state'] = None
    text = "🤖 *نظام التداول الخوارزمي الذكي*\n\nالأنظمة تعمل بكفاءة. اختر الإجراء:"
    await update.message.reply_text(text, reply_markup=get_main_menu(), parse_mode='Markdown')

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالجة الضغط على الأزرار"""
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == 'main_menu':
        context.user_data['state'] = None
        await query.edit_message_text("لوحة التحكم الرئيسية:", reply_markup=get_main_menu())
        
    elif data == 'coins':
        context.user_data['state'] = None
        await query.edit_message_text("🪙 *إدارة العملات*", reply_markup=get_coins_menu(), parse_mode='Markdown')
        
    elif data == 'report':
        await query.edit_message_text("📊 جاري تحليل صفقات التعلم...\n(النظام في مرحلة تجميع البيانات حالياً)", reply_markup=get_main_menu())
        
    elif data == 'add_coin':
        context.user_data['state'] = 'WAITING_COIN'
        await query.edit_message_text("✍️ أرسل رمز العملة الآن (مثال: BTCUSDT):")
        
    elif data == 'capital':
        context.user_data['state'] = 'WAITING_CAPITAL'
        await query.edit_message_text("💰 أرسل مبلغ رأس المال الجديد (مثال: 5000):")
        
    elif data == 'view_coins':
        # جلب العملات من قاعدة البيانات
        async with AsyncSessionLocal() as session:
            result = await session.execute(select(Watchlist.symbol))
            coins = result.scalars().all()
        
        if coins:
            text = "📋 *العملات المراقبة حالياً:*\n" + "\n".join([f"🔹 {c}" for c in coins])
        else:
            text = "📋 لا توجد عملات في قائمة المراقبة."
            
        await query.edit_message_text(text, reply_markup=get_coins_menu(), parse_mode='Markdown')

async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالجة النصوص المدخلة (اسم العملة أو رأس المال)"""
    if not await check_admin(update): return
    
    state = context.user_data.get('state')
    text = update.message.text.strip().upper()
    
    if state == 'WAITING_COIN':
        async with AsyncSessionLocal() as session:
            # التحقق مما إذا كانت العملة موجودة مسبقاً
            result = await session.execute(select(Watchlist).where(Watchlist.symbol == text))
            exists = result.scalars().first()
            
            if exists:
                await update.message.reply_text(f"⚠️ العملة {text} موجودة بالفعل!", reply_markup=get_coins_menu())
            else:
                new_coin = Watchlist(symbol=text)
                session.add(new_coin)
                await session.commit()
                await update.message.reply_text(f"✅ تم إضافة {text} بنجاح إلى رادار الحيتان!", reply_markup=get_coins_menu())
        context.user_data['state'] = None
        
    elif state == 'WAITING_CAPITAL':
        try:
            amount = float(text)
            await update.message.reply_text(f"✅ تم تحديث رأس المال إلى: ${amount:,.2f}", reply_markup=get_main_menu())
            context.user_data['state'] = None
        except ValueError:
            await update.message.reply_text("⚠️ يرجى إدخال رقم صحيح (مثال: 1000).")
    else:
        await update.message.reply_text("يرجى اختيار أمر من القائمة أولاً عبر /start")
