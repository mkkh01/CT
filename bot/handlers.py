# bot/handlers.py
from telegram import Update
from telegram.ext import ContextTypes
from bot.keyboards import get_main_menu, get_coins_menu, get_timeframe_menu
from config import ADMIN_ID
from database import AsyncSessionLocal, TrackedCoin, UserConfig
from sqlalchemy import select, delete
import requests

async def check_admin(update: Update) -> bool:
    user_id = update.effective_user.id
    if ADMIN_ID != 0 and user_id != ADMIN_ID:
        if update.message:
            await update.message.reply_text("⛔ عذراً، أنت غير مصرح لك.")
        return False
    return True

async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_admin(update): return
    context.user_data['state'] = None
    text = "🤖 *نظام التداول الخوارزمي المتقدم*\n\nمرحباً بك في لوحة التحكم المؤسسية:"
    await update.message.reply_text(text, reply_markup=get_main_menu(), parse_mode='Markdown')

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == 'main_menu':
        context.user_data['state'] = None
        await query.edit_message_text("لوحة التحكم الرئيسية:", reply_markup=get_main_menu())
        
    elif data == 'coins':
        context.user_data['state'] = None
        await query.edit_message_text("🪙 *إدارة العملات (ديناميكي)*", reply_markup=get_coins_menu(), parse_mode='Markdown')
        
    elif data == 'live_prices':
        await query.edit_message_text("⏳ جاري جلب الأسعار الحية من السوق...")
        async with AsyncSessionLocal() as session:
            result = await session.execute(select(TrackedCoin.symbol))
            symbols = result.scalars().all()
        
        if not symbols:
            await query.edit_message_text("⚠️ لا توجد عملات في قائمة المراقبة.", reply_markup=get_main_menu())
            return
            
        try:
            # جلب الأسعار من باينانس
            url = 'https://api.binance.com/api/v3/ticker/price'
            res = requests.get(url).json()
            prices = {item['symbol']: float(item['price']) for item in res}
            
            text = "📈 *الأسعار الحية للعملات المراقبة:*\n\n"
            for sym in symbols:
                price = prices.get(sym, 0.0)
                text += f"🔹 {sym}: `${price:,.6f}`\n"
            await query.edit_message_text(text, reply_markup=get_main_menu(), parse_mode='Markdown')
        except:
            await query.edit_message_text("⚠️ حدث خطأ أثناء الاتصال بالسوق.", reply_markup=get_main_menu())

    elif data == 'add_coin':
        context.user_data['state'] = 'WAITING_COIN_NAME'
        await query.edit_message_text("✍️ أرسل رمز العملة (مثال: BTCUSDT):")
        
    elif data == 'view_coins':
        async with AsyncSessionLocal() as session:
            result = await session.execute(select(TrackedCoin))
            coins = result.scalars().all()
        if coins:
            text = "📋 *إعدادات العملات الحالية:*\n\n"
            for c in coins:
                text += f"🔹 *{c.symbol}* | ⏱️ {c.timeframe} | 💰 ${c.allocated_capital}\n"
        else:
            text = "📋 لا توجد عملات في قائمة المراقبة."
        await query.edit_message_text(text, reply_markup=get_coins_menu(), parse_mode='Markdown')

    elif data == 'remove_coin':
        context.user_data['state'] = 'WAITING_REMOVE_COIN'
        await query.edit_message_text("🗑️ أرسل رمز العملة لحذفها:")

    # معالجة أزرار الإطار الزمني
    elif data.startswith('tf_'):
        parts = data.split('_')
        timeframe = parts[1]
        symbol = parts[2]
        
        capital = context.user_data.get('temp_capital', 100.0)
        
        async with AsyncSessionLocal() as session:
            new_coin = TrackedCoin(symbol=symbol, timeframe=timeframe, allocated_capital=capital)
            session.add(new_coin)
            await session.commit()
            
        await query.edit_message_text(f"✅ تم إضافة *{symbol}* بنجاح!\n💰 رأس المال: ${capital}\n⏱️ الإطار الزمني: {timeframe}", reply_markup=get_coins_menu(), parse_mode='Markdown')
        context.user_data['state'] = None

async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_admin(update): return
    state = context.user_data.get('state')
    text = update.message.text.strip().upper()
    
    if state == 'WAITING_COIN_NAME':
        async with AsyncSessionLocal() as session:
            result = await session.execute(select(TrackedCoin).where(TrackedCoin.symbol == text))
            if result.scalars().first():
                await update.message.reply_text(f"⚠️ العملة {text} موجودة بالفعل!", reply_markup=get_coins_menu())
                context.user_data['state'] = None
                return
                
        context.user_data['temp_symbol'] = text
        context.user_data['state'] = 'WAITING_COIN_CAPITAL'
        await update.message.reply_text(f"💰 ممتاز! كم رأس المال المخصص لعملة {text}؟ (مثال: 500)")
        
    elif state == 'WAITING_COIN_CAPITAL':
        try:
            capital = float(text)
            symbol = context.user_data.get('temp_symbol')
            context.user_data['temp_capital'] = capital
            
            await update.message.reply_text(f"⏱️ تم تحديد ${capital}. الآن اختر الإطار الزمني لعملة {symbol}:", reply_markup=get_timeframe_menu(symbol))
            context.user_data['state'] = None
        except ValueError:
            await update.message.reply_text("⚠️ يرجى إدخال رقم صحيح (مثال: 500).")

    elif state == 'WAITING_REMOVE_COIN':
        async with AsyncSessionLocal() as session:
            result = await session.execute(select(TrackedCoin).where(TrackedCoin.symbol == text))
            if not result.scalars().first():
                await update.message.reply_text(f"⚠️ العملة {text} غير موجودة!", reply_markup=get_coins_menu())
            else:
                await session.execute(delete(TrackedCoin).where(TrackedCoin.symbol == text))
                await session.commit()
                await update.message.reply_text(f"🗑️ تم حذف {text} بنجاح!", reply_markup=get_coins_menu())
        context.user_data['state'] = None
