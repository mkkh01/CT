from telegram import Update
from telegram.ext import ContextTypes
from bot.keyboards import get_main_menu, get_coins_menu, get_timeframe_menu
from config import ADMIN_ID
from database import AsyncSessionLocal, TrackedCoin, UserConfig, PaperTrade
from sqlalchemy import select, delete, func
import httpx  # تم استبدال requests بـ httpx لضمان سرعة واستقرار البوت الأيوسنكرونوس

async def check_admin(update: Update) -> bool:
    user_id = update.effective_user.id
    if ADMIN_ID != 0 and user_id != ADMIN_ID:
        if update.message:
            await update.message.reply_text("⛔ عذراً، أنت غير مصرح لك.")
        return False
    return True

async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_admin(update): return
    context.user_data["state"] = None
    text = "🤖 *نظام التداول الخوارزمي المتقدم (V3)*\n\nمرحباً بك! النظام الآن يراقب، يحلل، ويتعلم ذاتياً من كل صفقة."
    await update.message.reply_text(text, reply_markup=get_main_menu(), parse_mode='Markdown')

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == 'main_menu':
        context.user_data["state"] = None
        await query.edit_message_text("لوحة التحكم الرئيسية:", reply_markup=get_main_menu())
        
    elif data == 'coins':
        context.user_data["state"] = None
        await query.edit_message_text("🪙 *إدارة العملات والوقت*", reply_markup=get_coins_menu(), parse_mode='Markdown')
        
    elif data == 'report':
        async with AsyncSessionLocal() as session:
            won = await session.execute(select(func.count(PaperTrade.id)).where(PaperTrade.status == "WON"))
            lost = await session.execute(select(func.count(PaperTrade.id)).where(PaperTrade.status == "LOST"))
            open_t = await session.execute(select(func.count(PaperTrade.id)).where(PaperTrade.status == "OPEN"))
            
            won_count = won.scalar()
            lost_count = lost.scalar()
            open_count = open_t.scalar()
            
            last_trades = await session.execute(select(PaperTrade).where(PaperTrade.status != "OPEN").order_by(PaperTrade.closed_at.desc()).limit(5))
            trades = last_trades.scalars().all()

        text = (f"📊 *تقرير الأداء والتعلم الذاتي:*\n\n"
                f"✅ صفقات ناجحة: {won_count}\n"
                f"❌ صفقات خاسرة: {lost_count}\n"
                f"⏳ صفقات قيد المراقبة: {open_count}\n\n"
                f"🔍 *تحليل آخر العمليات:* \n")
        
        for t in trades:
            icon = "✅" if t.status == "WON" else "❌"
            type_t = "ظاهرة" if t.is_visible else "خفية"
            text += f"{icon} {t.symbol} ({type_t}): {t.analysis}\n"
            
        text += "\n--- النظام يقوم بتعديل خوارزمياته بناءً على هذه النتائج ---"
        await query.edit_message_text(text, reply_markup=get_main_menu(), parse_mode='Markdown')

    elif data == 'live_prices':
        await query.edit_message_text("⏳ جاري جلب الأسعار الحية...")
        async with AsyncSessionLocal() as session:
            result = await session.execute(select(TrackedCoin.symbol))
            symbols = result.scalars().all()
        
        if not symbols:
            await query.edit_message_text("⚠️ لا توجد عملات مراقبة.", reply_markup=get_main_menu())
            return
            
        try:
            url = 'https://api.binance.com/api/v3/ticker/price'
            async with httpx.AsyncClient() as client:
                res = await client.get(url)
                res_data = res.json()
            
            prices = {item['symbol']: float(item['price']) for item in res_data}
            text = "📈 *الأسعار الحية:*\n\n"
            for sym in symbols:
                price = prices.get(sym, 0.0)
                text += f"🔹 {sym}: `{price:,.8f}`\n"
            await query.edit_message_text(text, reply_markup=get_main_menu(), parse_mode='Markdown')
        except Exception as e:
            await query.edit_message_text(f"⚠️ خطأ في الاتصال: {e}", reply_markup=get_main_menu())

    elif data == 'add_coin':
        context.user_data["state"] = 'WAITING_COIN_NAME'
        await query.edit_message_text("✍️ أرسل رمز العملة (مثال: SOLUSDT):")
        
    elif data == 'view_coins':
        async with AsyncSessionLocal() as session:
            result = await session.execute(select(TrackedCoin))
            coins = result.scalars().all()
        text = "📋 *قائمة المراقبة:*\n\n" if coins else "📋 القائمة فارغة."
        for c in coins:
            text += f"🔹 *{c.symbol}* | {c.timeframe} | ${c.allocated_capital}\n"
        await query.edit_message_text(text, reply_markup=get_coins_menu(), parse_mode='Markdown')

    elif data == 'remove_coin':
        context.user_data["state"] = 'WAITING_REMOVE_COIN'
        await query.edit_message_text("🗑️ أرسل رمز العملة لحذفها:")

    elif data.startswith('tf_'):
        parts = data.split('_')
        timeframe, symbol = parts[1], parts[2]
        capital = context.user_data.get('temp_capital', 100.0)
        async with AsyncSessionLocal() as session:
            new_coin = TrackedCoin(symbol=symbol, timeframe=timeframe, allocated_capital=capital)
            session.add(new_coin)
            await session.commit()
        await query.edit_message_text(f"✅ تم إضافة {symbol} بنجاح!\n💰 ${capital} | ⏱️ {timeframe}", reply_markup=get_coins_menu(), parse_mode='Markdown')
        context.user_data["state"] = None

    elif data == 'start_sys':
        async with AsyncSessionLocal() as session:
            user_config = await session.execute(select(UserConfig).where(UserConfig.user_id == ADMIN_ID))
            config = user_config.scalars().first()
            if config:
                config.system_status = "running"
                await session.commit()
                await query.edit_message_text("▶️ تم تشغيل النظام بنجاح!", reply_markup=get_main_menu())
            else:
                await query.edit_message_text("⚠️ خطأ: لم يتم العثور على إعدادات المستخدم.", reply_markup=get_main_menu())

    elif data == 'stop_sys':
        async with AsyncSessionLocal() as session:
            user_config = await session.execute(select(UserConfig).where(UserConfig.user_id == ADMIN_ID))
            config = user_config.scalars().first()
            if config:
                config.system_status = "stopped"
                await session.commit()
                await query.edit_message_text("⏸️ تم إيقاف النظام بنجاح!", reply_markup=get_main_menu())
            else:
                await query.edit_message_text("⚠️ خطأ: لم يتم العثور على إعدادات المستخدم.", reply_markup=get_main_menu())

async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_admin(update): return
    state = context.user_data.get("state")
    text = update.message.text.strip().upper()
    
    if state == 'WAITING_COIN_NAME':
        context.user_data["temp_symbol"] = text
        context.user_data["state"] = 'WAITING_COIN_CAPITAL'
        await update.message.reply_text(f"💰 كم رأس المال المخصص لـ {text}؟")
        
    elif state == 'WAITING_COIN_CAPITAL':
        try:
            capital = float(text)
            symbol = context.user_data.get("temp_symbol")
            context.user_data["temp_capital"] = capital
            await update.message.reply_text(f"⏱️ اختر الإطار الزمني لـ {symbol}:", reply_markup=get_timeframe_menu(symbol))
            context.user_data["state"] = None
        except:
            await update.message.reply_text("⚠️ أدخل رقماً صحيحاً.")

    elif state == 'WAITING_REMOVE_COIN':
        async with AsyncSessionLocal() as session:
            await session.execute(delete(TrackedCoin).where(TrackedCoin.symbol == text))
            await session.commit()
            await update.message.reply_text(f"🗑️ تم حذف {text}!", reply_markup=get_coins_menu())
        context.user_data["state"] = None
