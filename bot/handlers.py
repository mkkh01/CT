from telegram import Update
from telegram.ext import ContextTypes
from bot.keyboards import get_main_menu, get_coins_menu, get_timeframe_menu
from config import ADMIN_ID
# استيراد النماذج الصحيحة من قاعدة البيانات المحدثة
from database import AsyncSessionLocal, TrackedCoin, UserConfig, PaperTrade
from sqlalchemy import select, delete, func
import httpx

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
    text = "🤖 *نظام التداول الخوارزمي المتقدم (V3)*\n\nمرحباً بك يا محمد! النظام الآن يراقب، يحلل، ويتعلم ذاتياً من كل صفقة."
    await update.message.reply_text(text, reply_markup=get_main_menu(), parse_mode='Markdown')

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    
    try:
        await query.answer()
    except Exception: pass

    try:
        if data == 'main_menu':
            context.user_data["state"] = None
            await query.edit_message_text("لوحة التحكم الرئيسية:", reply_markup=get_main_menu())
            
        elif data == 'coins':
            context.user_data["state"] = None
            await query.edit_message_text("🪙 *إدارة العملات والوقت*", reply_markup=get_coins_menu(), parse_mode='Markdown')
            
        elif data == 'private_trades':
            # --- برمجة زر الصفقات الخاصة الجديدة ---
            print("🌟 [LOG] جاري جلب الصفقات الخاصة عالية الثقة...")
            async with AsyncSessionLocal() as session:
                # جلب الصفقات المفتوحة التي ثقتها عالية (أعلى من 80% مثلاً)
                result = await session.execute(
                    select(PaperTrade).where(PaperTrade.status == "OPEN").order_by(PaperTrade.timestamp.desc()).limit(10)
                )
                trades = result.scalars().all()
            
            if not trades:
                await query.edit_message_text("🔍 لا توجد صفقات خاصة نشطة حالياً. الرادار يبحث عن فرص ذهبية...", reply_markup=get_main_menu())
                return

            text = "🌟 *أحدث الصفقات الخاصة (فرص النخبة):*\n\n"
            for t in trades:
                # نعتبر الصفقة خاصة إذا لم تكن مجرد "تدريب صامت" (أي ثقتها عالية)
                text += f"🔹 *{t.symbol}* | {t.type}\n💰 السعر: `{t.entry_price}`\n🎯 الهدف: `{t.take_profit}`\n🛡️ الوقف: `{t.stop_loss}`\n\n"
            
            await query.edit_message_text(text, reply_markup=get_main_menu(), parse_mode='Markdown')

        elif data == 'report':
            async with AsyncSessionLocal() as session:
                won = await session.execute(select(func.count(PaperTrade.id)).where(PaperTrade.status == "WON"))
                lost = await session.execute(select(func.count(PaperTrade.id)).where(PaperTrade.status == "LOST"))
                open_t = await session.execute(select(func.count(PaperTrade.id)).where(PaperTrade.status == "OPEN"))
                
                won_count = won.scalar() or 0
                lost_count = lost.scalar() or 0
                open_count = open_t.scalar() or 0
                
                # حساب نسبة النجاح
                total_closed = won_count + lost_count
                win_rate = (won_count / total_closed * 100) if total_closed > 0 else 0

                last_trades = await session.execute(select(PaperTrade).where(PaperTrade.status != "OPEN").order_by(PaperTrade.closed_at.desc()).limit(5))
                trades = last_trades.scalars().all()

            text = (f"📊 *تقرير الأداء والتعلم الذاتي V3:*\n\n"
                    f"✅ صفقات ناجحة: {won_count}\n"
                    f"❌ صفقات خاسرة: {lost_count}\n"
                    f"⏳ صفقات قيد التدريب: {open_count}\n"
                    f"📈 نسبة النجاح: %{win_rate:.1f}\n\n"
                    f"🔍 *تحليل جودة الصفقات الأخيرة:* \n")
            
            for t in trades:
                icon = "✅" if t.status == "WON" else "❌"
                text += f"{icon} {t.symbol}: {t.status} (سعر الدخول: {t.entry_price})\n"
                
            text += "\n--- النظام يطور استراتيجياته بناءً على هذه النتائج ---"
            await query.edit_message_text(text, reply_markup=get_main_menu(), parse_mode='Markdown')

        elif data == 'live_prices':
            async with AsyncSessionLocal() as session:
                result = await session.execute(select(TrackedCoin.symbol))
                symbols = result.scalars().all()
            
            if not symbols:
                await query.edit_message_text("⚠️ لا توجد عملات مراقبة حالياً.", reply_markup=get_main_menu())
                return
                
            await query.edit_message_text("⏳ جاري جلب الأسعار الحية...")
            try:
                url = 'https://api.binance.com/api/v3/ticker/price'
                async with httpx.AsyncClient() as client:
                    res = await client.get(url)
                    prices = {item['symbol']: float(item['price']) for item in res.json()}
                
                text = "📈 *الأسعار الحية (Binance):*\n\n"
                for sym in symbols:
                    price = prices.get(sym, 0.0)
                    text += f"🔹 {sym}: `{price:,.4f}`\n"
                await query.edit_message_text(text, reply_markup=get_main_menu(), parse_mode='Markdown')
            except Exception as e:
                await query.edit_message_text(f"⚠️ خطأ اتصال: {e}", reply_markup=get_main_menu())

        elif data == 'add_coin':
            context.user_data["state"] = 'WAITING_COIN_NAME'
            await query.edit_message_text("✍️ أرسل رمز العملة المراد مراقبتها (مثال: SOLUSDT):")
            
        elif data == 'view_coins':
            async with AsyncSessionLocal() as session:
                result = await session.execute(select(TrackedCoin))
                coins = result.scalars().all()
            text = "📋 *قائمة المراقبة النشطة:*\n\n" if coins else "📋 القائمة فارغة."
            for c in coins:
                text += f"🔹 *{c.symbol}* | الإطار: {c.timeframe} | الرأس مال: ${c.allocated_capital}\n"
            await query.edit_message_text(text, reply_markup=get_coins_menu(), parse_mode='Markdown')

        elif data == 'remove_coin':
            context.user_data["state"] = 'WAITING_REMOVE_COIN'
            await query.edit_message_text("🗑️ أرسل رمز العملة التي ترغب في حذفها:")

        elif data.startswith('tf_'):
            parts = data.split('_')
            timeframe, symbol = parts[1], parts[2]
            capital = context.user_data.get('temp_capital', 100.0)
            async with AsyncSessionLocal() as session:
                new_coin = TrackedCoin(symbol=symbol, timeframe=timeframe, allocated_capital=capital)
                session.add(new_coin)
                await session.commit()
            await update.effective_message.edit_text(f"✅ تم إضافة {symbol} بنجاح!\n⏱️ الإطار الزمني: {timeframe}", reply_markup=get_coins_menu())
            context.user_data["state"] = None

    except Exception as e:
        print(f"🚨 [ERROR] Button Handler: {e}")

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
            context.user_data["temp_capital"] = float(text)
            symbol = context.user_data.get("temp_symbol")
            await update.message.reply_text(f"⏱️ اختر الإطار الزمني لـ {symbol}:", reply_markup=get_timeframe_menu(symbol))
            context.user_data["state"] = None
        except:
            await update.message.reply_text("⚠️ أدخل رقماً صحيحاً.")

    elif state == 'WAITING_REMOVE_COIN':
        async with AsyncSessionLocal() as session:
            await session.execute(delete(TrackedCoin).where(TrackedCoin.symbol == text))
            await session.commit()
            await update.message.reply_text(f"🗑️ تم حذف {text} بنجاح!", reply_markup=get_coins_menu())
        context.user_data["state"] = None
