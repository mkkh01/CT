from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from datetime import datetime
from sqlalchemy import select, desc, func, delete
import httpx

# استيراد الإعدادات والكيانات الخاصة بك
from config import ADMIN_ID
from database import AsyncSessionLocal, TrackedCoin, UserConfig, PaperTrade
from bot.keyboards import get_main_menu, get_coins_menu, get_private_trades_menu, get_timeframe_menu

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
    text = "🤖 *نظام التداول الخوارزمي المتقدم (V3)*\n\nمرحباً بك يا محمد! النظام جاهز الآن للعمل المستقر والتعلم التحليلي."
    await update.message.reply_text(text, reply_markup=get_main_menu(), parse_mode='Markdown')

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    
    try:
        await query.answer()
    except: pass

    if data == 'main_menu':
        await query.edit_message_text("لوحة التحكم الرئيسية:", reply_markup=get_main_menu())
            
    elif data == 'private_trades':
        # يفتح القائمة الفرعية الثلاثية (تشغيل، إيقاف، تقرير لحظي)
        await query.edit_message_text(
            "🌟 *مركز التحكم بالصفقات الخاصة*\n\nهنا يمكنك إدارة إشارات النخبة وطلب تقارير الأداء اللحظية.",
            reply_markup=get_private_trades_menu(),
            parse_mode='Markdown'
        )

    elif data == 'elite_on' or data == 'elite_off':
        is_on = (data == 'elite_on')
        async with AsyncSessionLocal() as session:
            res = await session.execute(select(UserConfig).where(UserConfig.telegram_id == ADMIN_ID))
            cfg = res.scalars().first()
            if cfg:
                cfg.elite_enabled = is_on
                await session.commit()
        
        status_text = "🟢 تم تفعيل إشارات التداول" if is_on else "🔴 تم إيقاف إشارات التداول"
        await query.edit_message_text(f"{status_text}\n\nالنظام سيستمر في التحليل ولكن الإشعارات ستتأثر باختيارك.", reply_markup=get_main_menu())

    elif data == 'elite_instant_report':
        # تقرير الصفقات المضمونة (نخبة) حتى لحظة الضغط
        async with AsyncSessionLocal() as session:
            res = await session.execute(
                select(PaperTrade).where(PaperTrade.is_elite == True, PaperTrade.status != "OPEN")
            )
            trades = res.scalars().all()
            won = len([t for t in trades if t.status == "WON"])
            lost = len([t for t in trades if t.status == "LOST"])
            total_pnl = sum([t.pnl for t in trades])
            
            report = (
                f"📋 *التقرير اللحظي (نخبة)*\n"
                f"━━━━━━━━━━━━━━\n"
                f"✅ ناجحة: `{won}` | ❌ خاسرة: `{lost}`\n"
                f"💰 إجمالي الربح: `{total_pnl:.2f}$`\n"
                f"━━━━━━━━━━━━━━\n"
                f"⏱️ تم الحساب في: `{datetime.now().strftime('%H:%M:%S')}`"
            )
            await query.edit_message_text(report, reply_markup=get_main_menu(), parse_mode='Markdown')

    elif data == 'report':
        # تقرير التعلم الخفي (خاص بالصفقات غير المضمونة)
        async with AsyncSessionLocal() as session:
            res = await session.execute(
                select(PaperTrade).where(PaperTrade.is_elite == False, PaperTrade.status != "OPEN")
                .order_by(desc(PaperTrade.closed_at)).limit(5)
            )
            trades = res.scalars().all()
            
            text = "🧠 *سجل التعلم الخفي (التدريب)*\n━━━━━━━━━━━━━━\n"
            if not trades:
                text += "▫️ لا توجد بيانات تدريب كافية حالياً."
            for t in trades:
                icon = "🔬" if t.status == "WON" else "📉"
                text += f"{icon} *{t.symbol}*: {t.result_reason or 'تحليل آلي'}\n"
            
            await query.edit_message_text(text, reply_markup=get_main_menu(), parse_mode='Markdown')

    elif data == 'coins':
        await query.edit_message_text("🪙 *إدارة العملات والوقت*", reply_markup=get_coins_menu(), parse_mode='Markdown')

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
            await query.edit_message_text("⚠️ فشل الاتصال مع Binance.", reply_markup=get_main_menu())

    elif data == 'add_coin':
        context.user_data["state"] = 'WAITING_COIN_NAME'
        await query.edit_message_text("✍️ أرسل رمز العملة (مثال: SOLUSDT):")

async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_admin(update): return
    text = update.message.text.strip()
    
    # التعامل مع أزرار التشغيل/الإيقاف السفلية للتعلم الخفي
    if text == "▶️ بدء التعلم الخفي":
        async with AsyncSessionLocal() as session:
            res = await session.execute(select(UserConfig).where(UserConfig.telegram_id == ADMIN_ID))
            cfg = res.scalars().first()
            if cfg:
                cfg.is_active = True
                await session.commit()
        await update.message.reply_text("🚀 تم بدء محرك التعلم الخفي. النظام يراقب الآن بصمت.")
        return

    elif text == "⏸️ إيقاف التعلم الخفي":
        async with AsyncSessionLocal() as session:
            res = await session.execute(select(UserConfig).where(UserConfig.telegram_id == ADMIN_ID))
            cfg = res.scalars().first()
            if cfg:
                cfg.is_active = False
                await session.commit()
        await update.message.reply_text("⏸️ تم إيقاف محرك التعلم.")
        return

    # التعامل مع حالات إدخال العملات
    state = context.user_data.get("state")
    if state == 'WAITING_COIN_NAME':
        context.user_data["temp_symbol"] = text.upper()
        context.user_data["state"] = 'WAITING_COIN_CAPITAL'
        await update.message.reply_text(f"💰 رأس المال المخصص لـ {text.upper()}؟")
    elif state == 'WAITING_COIN_CAPITAL':
        try:
            capital = float(text)
            symbol = context.user_data["temp_symbol"]
            async with AsyncSessionLocal() as session:
                new_coin = TrackedCoin(symbol=symbol, allocated_capital=capital)
                session.add(new_coin)
                await session.commit()
            await update.message.reply_text(f"✅ تمت إضافة {symbol} برأس مال ${capital}", reply_markup=get_main_menu())
            context.user_data["state"] = None
        except:
            await update.message.reply_text("⚠️ خطأ في الرقم، حاول ثانية.")
