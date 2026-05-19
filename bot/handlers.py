# bot/handlers.py
from telegram import Update
from telegram.ext import ContextTypes
from bot.keyboards import get_main_menu, get_coins_menu
from config import ADMIN_ID
from database import AsyncSessionLocal, Watchlist, UserConfig
from sqlalchemy import select, delete

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
    
    context.user_data['state'] = None
    text = "🤖 *نظام التداول الخوارزمي الذكي*\n\nالأنظمة تعمل بكفاءة. اختر الإجراء:"
    await update.message.reply_text(text, reply_markup=get_main_menu(), parse_mode='Markdown')

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالجة الضغط على جميع الأزرار"""
    query = update.callback_query
    await query.answer()
    data = query.data

    # --- القوائم الرئيسية ---
    if data == 'main_menu':
        context.user_data['state'] = None
        await query.edit_message_text("لوحة التحكم الرئيسية:", reply_markup=get_main_menu())
        
    elif data == 'coins':
        context.user_data['state'] = None
        await query.edit_message_text("🪙 *إدارة العملات*", reply_markup=get_coins_menu(), parse_mode='Markdown')
        
    # --- إدارة النظام (تشغيل / إيقاف) ---
    elif data == 'start_sys':
        async with AsyncSessionLocal() as session:
            # تحديث حالة النظام في قاعدة البيانات
            result = await session.execute(select(UserConfig).where(UserConfig.telegram_id == update.effective_user.id))
            config = result.scalars().first()
            if not config:
                config = UserConfig(telegram_id=update.effective_user.id, is_active=True)
                session.add(config)
            else:
                config.is_active = True
            await session.commit()
        await query.edit_message_text("🟢 *تم تشغيل النظام!*\nالذكاء الاصطناعي ورادار الحيتان يراقبان السوق الآن.", reply_markup=get_main_menu(), parse_mode='Markdown')

    elif data == 'stop_sys':
        async with AsyncSessionLocal() as session:
            result = await session.execute(select(UserConfig).where(UserConfig.telegram_id == update.effective_user.id))
            config = result.scalars().first()
            if config:
                config.is_active = False
                await session.commit()
        await query.edit_message_text("🔴 *تم إيقاف النظام مؤقتاً.*\nلن يتم فتح أي صفقات جديدة حتى تقوم بتشغيله.", reply_markup=get_main_menu(), parse_mode='Markdown')

    # --- التقارير ورأس المال ---
    elif data == 'report':
        await query.edit_message_text("📊 *التقرير الخفي:*\nالنظام حالياً في مرحلة تجميع البيانات ومراقبة الحيتان. سيتم عرض الصفقات الوهمية هنا قريباً.", reply_markup=get_main_menu(), parse_mode='Markdown')
        
    elif data == 'capital':
        context.user_data['state'] = 'WAITING_CAPITAL'
        await query.edit_message_text("💰 أرسل مبلغ رأس المال الجديد (مثال: 5000):")
        
    # --- إدارة العملات ---
    elif data == 'add_coin':
        context.user_data['state'] = 'WAITING_COIN'
        await query.edit_message_text("✍️ أرسل رمز العملة لإضافتها (مثال: BTCUSDT):")
        
    elif data == 'remove_coin':
        context.user_data['state'] = 'WAITING_REMOVE_COIN'
        await query.edit_message_text("🗑️ أرسل رمز العملة لحذفها (مثال: BTCUSDT):")
        
    elif data == 'view_coins':
        async with AsyncSessionLocal() as session:
            result = await session.execute(select(Watchlist.symbol))
            coins = result.scalars().all()
        
        if coins:
            text = "📋 *العملات المراقبة حالياً:*\n" + "\n".join([f"🔹 {c}" for c in coins])
        else:
            text = "📋 لا توجد عملات في قائمة المراقبة."
        await query.edit_message_text(text, reply_markup=get_coins_menu(), parse_mode='Markdown')

async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالجة النصوص المدخلة (إضافة/حذف عملة أو رأس المال)"""
    if not await check_admin(update): return
    
    state = context.user_data.get('state')
    text = update.message.text.strip().upper()
    
    if state == 'WAITING_COIN':
        async with AsyncSessionLocal() as session:
            result = await session.execute(select(Watchlist).where(Watchlist.symbol == text))
            if result.scalars().first():
                await update.message.reply_text(f"⚠️ العملة {text} موجودة بالفعل!", reply_markup=get_coins_menu())
            else:
                session.add(Watchlist(symbol=text))
                await session.commit()
                await update.message.reply_text(f"✅ تم إضافة {text} بنجاح!", reply_markup=get_coins_menu())
        context.user_data['state'] = None
        
    elif state == 'WAITING_REMOVE_COIN':
        async with AsyncSessionLocal() as session:
            result = await session.execute(select(Watchlist).where(Watchlist.symbol == text))
            if not result.scalars().first():
                await update.message.reply_text(f"⚠️ العملة {text} غير موجودة في القائمة!", reply_markup=get_coins_menu())
            else:
                await session.execute(delete(Watchlist).where(Watchlist.symbol == text))
                await session.commit()
                await update.message.reply_text(f"🗑️ تم حذف {text} بنجاح!", reply_markup=get_coins_menu())
        context.user_data['state'] = None
        
    elif state == 'WAITING_CAPITAL':
        try:
            amount = float(text)
            async with AsyncSessionLocal() as session:
                result = await session.execute(select(UserConfig).where(UserConfig.telegram_id == update.effective_user.id))
                config = result.scalars().first()
                if not config:
                    config = UserConfig(telegram_id=update.effective_user.id, paper_capital=amount)
                    session.add(config)
                else:
                    config.paper_capital = amount
                await session.commit()
            await update.message.reply_text(f"✅ تم تحديث رأس المال إلى: ${amount:,.2f}", reply_markup=get_main_menu())
            context.user_data['state'] = None
        except ValueError:
            await update.message.reply_text("⚠️ يرجى إدخال رقم صحيح (مثال: 1000).")
    else:
        await update.message.reply_text("يرجى اختيار أمر من القائمة أولاً عبر /start")
