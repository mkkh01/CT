from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from bot.keyboards import get_main_menu, get_coins_menu, get_timeframe_menu
from config import ADMIN_ID
from database import AsyncSessionLocal, TrackedCoin, UserConfig, PaperTrade
from sqlalchemy import select, delete, func, desc
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
    text = "🤖 *نظام التداول الخوارزمي المتقدم (V3)*\n\nمرحباً بك يا محمد! النظام جاهز الآن للعمل المستقر والتعلم التحليلي."
    await update.message.reply_text(text, reply_markup=get_main_menu(), parse_mode='Markdown')

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    
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

        elif data == 'private_trades':
            # --- منطق زر صفقات النخبة الجديد (تحكم + تقرير سريع) ---
            async with AsyncSessionLocal() as session:
                res = await session.execute(select(UserConfig).where(UserConfig.telegram_id == ADMIN_ID))
                cfg = res.scalars().first()
                if not cfg:
                    cfg = UserConfig(telegram_id=ADMIN_ID, is_active=True, elite_enabled=True)
                    session.add(cfg)
                
                # تبديل الحالة عند الضغط
                cfg.elite_enabled = not cfg.elite_enabled
                await session.commit()
                
                status_icon = "🟢 نشط" if cfg.elite_enabled else "🔴 متوقف"
                
                # جلب آخر نتائج النخبة والتعلم
                elite_trades = await session.execute(select(PaperTrade).where(PaperTrade.is_elite == True).order_by(desc(PaperTrade.timestamp)).limit(3))
                learning_trades = await session.execute(select(PaperTrade).where(PaperTrade.is_elite == False).order_by(desc(PaperTrade.timestamp)).limit(3))
                
                text = f"🌟 *مركز صفقات النخبة* {status_icon}\n"
                text += f"━━━━━━━━━━━━━━\n"
                text += "📝 *أحدث نتائج النخبة (مع الأسباب):*\n"
                e_list = elite_trades.scalars().all()
                if not e_list: text += "▫️ لا توجد بيانات حالياً.\n"
                for t in e_list:
                    icon = "✅" if t.status == "WON" else "❌" if t.status == "LOST" else "⏳"
                    reason = t.result_reason if t.result_reason else "تحت المراقبة..."
                    text += f"{icon} *{t.symbol}*: {reason}\n"
                
                text += "\n🧠 *سجلات التعلم (الصفقات المخفية):*\n"
                l_list = learning_trades.scalars().all()
                if not l_list: text += "▫️ في مرحلة جمع البيانات...\n"
                for t in l_list:
                    text += f"🔬 *{t.symbol}*: {t.result_reason or 'جاري التحليل...'}\n"
                
                text += f"\n━━━━━━━━━━━━━━\n💡 _تم تبديل حالة الإشعارات بنجاح._"
                await query.edit_message_text(text, reply_markup=get_main_menu(), parse_mode='Markdown')

        elif data == 'report':
            # --- التقرير الشامل والموسع ---
            async with AsyncSessionLocal() as session:
                won = await session.execute(select(func.count(PaperTrade.id)).where(PaperTrade.status == "WON"))
                lost = await session.execute(select(func.count(PaperTrade.id)).where(PaperTrade.status == "LOST"))
                
                # جلب آخر 5 صفقات مغلقة للتحليل
                last_trades = await session.execute(
                    select(PaperTrade).where(PaperTrade.status != "OPEN").order_by(desc(PaperTrade.closed_at)).limit(5)
                )
                trades = last_trades.scalars().all()

                won_c, lost_c = won.scalar() or 0, lost.scalar() or 0
                total = won_c + lost_c
                rate = (won_c / total * 100) if total > 0 else 0

            text = f"📊 *تقرير الأداء والتحليل الشامل (V3)*\n"
            text += f"━━━━━━━━━━━━━━\n"
            text += f"✅ ناجحة: `{won_c}` | ❌ خاسرة: `{lost_c}`\n"
            text += f"📈 دقة النظام العامة: `{rate:.1f}%`\n\n"
            text += "🔍 *التحليل التفصيلي لآخر العمليات:*\n"
            
            for t in trades:
                icon = "✅" if t.status == "WON" else "❌"
                text += f"{icon} *{t.symbol}* ({t.type})\n"
                text += f"└ 💡 _السبب: {t.result_reason or 'غير محدد'}_ \n"
                text += f"└ 📈 الثقة: `{t.confidence}%` | الربح: `{t.pnl:.2f}$`\n\n"
            
            text += "🤖 _النظام يحدّث استراتيجياته تلقائياً بناءً على هذه الأسباب._"
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
                await query.edit_message_text("⚠️ فشل الاتصال مع Binance.", reply_markup=get_main_menu())

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
