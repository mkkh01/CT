from telegram import Update
from telegram.ext import ContextTypes
from bot.keyboards import get_main_menu, get_coins_menu, get_timeframe_menu
from config import ADMIN_ID
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
    text = "🤖 *نظام التداول الخوارزمي المتقدم (V3)*\n\nمرحباً بك يا محمد! النظام جاهز الآن للعمل المستقر."
    await update.message.reply_text(text, reply_markup=get_main_menu(), parse_mode='Markdown')

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    
    # 1. الاستجابة الفورية لتيليجرام لفك تعليق الزر
    try:
        await query.answer()
    except: pass

    try:
        if data == 'main_menu':
            context.user_data["state"] = None
            await query.edit_message_text("لوحة التحكم الرئيسية:", reply_markup=get_main_menu())
            
        elif data == 'coins':
            context.user_data["state"] = None
            await query.edit_message_text("🪙 *إدارة العملات والوقت*", reply_markup=get_coins_menu(), parse_mode='Markdown')

        elif data == 'capital':
            context.user_data["state"] = 'WAITING_TOTAL_CAPITAL'
            await query.edit_message_text("💰 *إدارة رأس المال الكلي:*\n\nأرسل قيمة رأس المال الجديد (بالدولار):", parse_mode='Markdown')
            
        elif data == 'start_sys':
            async with AsyncSessionLocal() as session:
                res = await session.execute(select(UserConfig).where(UserConfig.telegram_id == ADMIN_ID))
                cfg = res.scalars().first()
                if cfg: cfg.is_active = True
                else: session.add(UserConfig(telegram_id=ADMIN_ID, is_active=True))
                await session.commit()
            await query.edit_message_text("▶️ تم تشغيل النظام بنجاح!", reply_markup=get_main_menu())

        elif data == 'stop_sys':
            async with AsyncSessionLocal() as session:
                res = await session.execute(select(UserConfig).where(UserConfig.telegram_id == ADMIN_ID))
                cfg = res.scalars().first()
                if cfg: cfg.is_active = False
                await session.commit()
            await query.edit_message_text("⏸️ تم إيقاف النظام عن البحث.", reply_markup=get_main_menu())
            
        elif data == 'private_trades':
            async with AsyncSessionLocal() as session:
                result = await session.execute(
                    select(PaperTrade).where(PaperTrade.status == "OPEN").order_by(PaperTrade.timestamp.desc()).limit(10)
                )
                trades = result.scalars().all()
            
            if not trades:
                await query.edit_message_text("🔍 لا توجد صفقات عالية الثقة حالياً.", reply_markup=get_main_menu())
                return

            text = "🌟 *أحدث الصفقات الخاصة (V3):*\n\n"
            for t in trades:
                text += f"🔹 *{t.symbol}* | {t.type}\n💰 السعر: `{t.entry_price}`\n\n"
            await query.edit_message_text(text, reply_markup=get_main_menu(), parse_mode='Markdown')

        elif data == 'report':
            async with AsyncSessionLocal() as session:
                won = await session.execute(select(func.count(PaperTrade.id)).where(PaperTrade.status == "WON"))
                lost = await session.execute(select(func.count(PaperTrade.id)).where(PaperTrade.status == "LOST"))
                won_count, lost_count = won.scalar() or 0, lost.scalar() or 0
                
                last_trades = await session.execute(select(PaperTrade).where(PaperTrade.status != "OPEN").order_by(PaperTrade.closed_at.desc()).limit(5))
                trades = last_trades.scalars().all()

            text = f"📊 *تقرير الأداء:*\n✅ ناجحة: {won_count}\n❌ خاسرة: {lost_count}\n\n🔍 آخر العمليات:\n"
            for t in trades:
                text += f"{'✅' if t.status=='WON' else '❌'} {t.symbol} | {t.status}\n"
            await query.edit_message_text(text, reply_markup=get_main_menu(), parse_mode='Markdown')

        elif data == 'live_prices':
            await query.edit_message_text("⏳ جاري جلب الأسعار...")
            try:
                async with AsyncSessionLocal() as session:
                    res = await session.execute(select(TrackedCoin.symbol))
                    symbols = res.scalars().all()
                
                if not symbols:
                    await query.edit_message_text("⚠️ لا توجد عملات مراقبة.", reply_markup=get_main_menu())
                    return

                async with httpx.AsyncClient() as client:
                    r = await client.get('https://api.binance.com/api/v3/ticker/price')
                    p_map = {i['symbol']: i['price'] for i in r.json()}
                
                text = "📈 *الأسعار الحية:*\n\n"
                for s in symbols:
                    text += f"🔹 {s}: `{p_map.get(s, 'N/A')}`\n"
                await query.edit_message_text(text, reply_markup=get_main_menu(), parse_mode='Markdown')
            except:
                await query.edit_message_text("⚠️ فشل جلب الأسعار (تأكد من رفع الحظر).", reply_markup=get_main_menu())

        elif data == 'add_coin':
            context.user_data["state"] = 'WAITING_COIN_NAME'
            await query.edit_message_text("✍️ أرسل رمز العملة (مثال: SOLUSDT):")
            
        elif data == 'view_coins':
            async with AsyncSessionLocal() as session:
                res = await session.execute(select(TrackedCoin))
                coins = res.scalars().all()
            text = "📋 *قائمة المراقبة:*\n\n" + "\n".join([f"🔹 {c.symbol}" for c in coins]) if coins else "القائمة فارغة."
            await query.edit_message_text(text, reply_markup=get_coins_menu(), parse_mode='Markdown')

        elif data == 'remove_coin':
            context.user_data["state"] = 'WAITING_REMOVE_COIN'
            await query.edit_message_text("🗑️ أرسل رمز العملة لحذفها:")

        elif data.startswith('tf_'):
            p = data.split('_')
            async with AsyncSessionLocal() as session:
                session.add(TrackedCoin(symbol=p[2], timeframe=p[1], allocated_capital=context.user_data.get('temp_capital', 100.0)))
                await session.commit()
            await query.edit_message_text(f"✅ تم إضافة {p[2]} بنجاح!", reply_markup=get_coins_menu())
            context.user_data["state"] = None

    except Exception as e:
        print(f"🚨 خطأ في الأزرار: {e}")

async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_admin(update): return
    state = context.user_data.get("state")
    text = update.message.text.strip().upper()
    
    try:
        if state == 'WAITING_COIN_NAME':
            context.user_data["temp_symbol"] = text
            context.user_data["state"] = 'WAITING_COIN_CAPITAL'
            await update.message.reply_text(f"💰 رأس المال المخصص لـ {text}؟")
            
        elif state == 'WAITING_COIN_CAPITAL':
            context.user_data["temp_capital"] = float(text)
            await update.message.reply_text(f"⏱️ اختر الإطار الزمني:", reply_markup=get_timeframe_menu(context.user_data["temp_symbol"]))
            context.user_data["state"] = None

        elif state == 'WAITING_TOTAL_CAPITAL':
            async with AsyncSessionLocal() as session:
                res = await session.execute(select(UserConfig).where(UserConfig.telegram_id == ADMIN_ID))
                cfg = res.scalars().first()
                if cfg: cfg.paper_capital = float(text)
                else: session.add(UserConfig(telegram_id=ADMIN_ID, paper_capital=float(text), is_active=False))
                await session.commit()
            await update.message.reply_text(f"✅ تم تحديث رأس المال إلى ${text}", reply_markup=get_main_menu())
            context.user_data["state"] = None

        elif state == 'WAITING_REMOVE_COIN':
            async with AsyncSessionLocal() as session:
                await session.execute(delete(TrackedCoin).where(TrackedCoin.symbol == text))
                await session.commit()
            await update.message.reply_text(f"🗑️ تم حذف {text}", reply_markup=get_coins_menu())
            context.user_data["state"] = None
    except:
        await update.message.reply_text("⚠️ تأكد من إدخال بيانات صحيحة.")
