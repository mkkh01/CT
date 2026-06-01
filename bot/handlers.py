from telegram import Update
from telegram.ext import (
    ContextTypes, ConversationHandler, CommandHandler,
    MessageHandler, CallbackQueryHandler, filters
)
from telegram.error import Conflict, NetworkError, TimedOut
from datetime import datetime
from sqlalchemy import select, delete, func
from config import ADMIN_ID
# ✅ استيراد جميع الجداول الموجودة لديك
from database import AsyncSessionLocal, TrackedCoin, UserConfig, PaperTrade
from bot.keyboards import get_main_menu, get_coins_menu, get_private_trades_menu, get_timeframe_menu
import yfinance as yf

# تعريف حالات المحادثة لإضافة العملة
NAME, CAPITAL, TIMEFRAME = range(3)

async def check_admin(update: Update) -> bool:
    user_id = update.effective_user.id
    return ADMIN_ID != 0 and user_id == ADMIN_ID

# معالج الأخطاء العام
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    error = context.error
    print(f"⚠️ نظام: حدث خطأ -> {str(error)}")
    if isinstance(error, Conflict):
        return
    elif isinstance(error, (NetworkError, TimedOut)):
        return
    if update and isinstance(update, Update) and update.effective_message:
        try:
            await update.effective_message.reply_text("❌ حدث خطأ بسيط، يرجى المحاولة مجدداً.")
        except:
            pass


async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_admin(update):
        return
    await update.message.reply_text(
        "🤖 *نظام التداول V3*\nمرحباً بك، اختر من القائمة أدناه:",
        reply_markup=get_main_menu(),
        parse_mode='Markdown'
    )

# --- منطق إضافة عملة جديدة ---
async def start_add_coin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.message:
        await query.message.edit_text("✍️ أرسل رمز العملة بصيغة صحيحة (مثل: BTCUSDT):")
    return NAME

async def get_coin_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return NAME
    symbol_input = update.message.text.strip().upper()
    if not symbol_input.isalnum():
        await update.message.reply_text("⚠️ الرمز غير صالح! أعد المحاولة:")
        return NAME
    context.user_data["symbol"] = symbol_input
    await update.message.reply_text("💰 أدخل رأس المال المخصص لهذه العملة (رقم فقط):")
    return CAPITAL

async def get_capital(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return CAPITAL
    try:
        capital_value = float(update.message.text.strip())
        if capital_value <= 0:
            raise ValueError("قيمة صفر")
        context.user_data["capital"] = capital_value
        await update.message.reply_text("⏱️ اختر الإطار الزمني المناسب:", reply_markup=get_timeframe_menu())
        return TIMEFRAME
    except:
        await update.message.reply_text("⚠️ قيمة غير صالحة! أدخل رقماً موجباً صحيحاً:")
        return CAPITAL

async def get_timeframe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not query.message:
        return ConversationHandler.END
    tf = query.data.replace("tf_", "")

    async with AsyncSessionLocal() as session:
        new_coin = TrackedCoin(
            symbol=context.user_data["symbol"],
            allocated_capital=context.user_data["capital"],
            timeframe=tf
        )
        session.add(new_coin)
        await session.commit()

    await query.edit_message_text(
        f"✅ تمت إضافة العملة إلى قاعدة البيانات بنجاح!\n\n"
        f"🪙 العملة: *{context.user_data['symbol']}*\n"
        f"💵 رأس المال: *{context.user_data['capital']}*\n"
        f"⏱️ الإطار: *{tf}*",
        parse_mode='Markdown'
    )
    await context.bot.send_message(update.effective_chat.id, "🏠 العودة للقائمة الرئيسية:", reply_markup=get_main_menu())
    context.user_data.clear()
    return ConversationHandler.END

# --- معالج الأزرار الرئيسية ---
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not query.message:
        return
    data = query.data

    if data == 'main_menu':
        try: await query.message.delete()
        except: pass
        await context.bot.send_message(update.effective_chat.id, "🏠 القائمة الرئيسية:", reply_markup=get_main_menu())

    elif data == 'private_trades':
        await query.edit_message_text(
            "🌟 *مركز التحكم والصفقات الخاصة*\nتحكم في نظام الإشارات وعرض التقارير:",
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
            else:
                cfg = UserConfig(telegram_id=ADMIN_ID, elite_enabled=is_on)
                session.add(cfg)
            await session.commit()
        status = "مُفعل ✅" if is_on else "معطل ❌"
        await query.edit_message_text(f"✅ تم تحديث الحالة: نظام الإشارات أصبح {status}")

    elif data == 'coins':
        await query.edit_message_text("🪙 إدارة العملات المضافة:", reply_markup=get_coins_menu())

    elif data == 'add_coin':
        await query.edit_message_text("✍️ أرسل رمز العملة (مثال: BTCUSDT):")
        return NAME

    elif data == 'remove_coin':
        async with AsyncSessionLocal() as session:
            coins = await session.execute(select(TrackedCoin.id, TrackedCoin.symbol))
            coins_list = coins.all()
            if not coins_list:
                await query.edit_message_text("📋 لا توجد عملات مضافة حالياً للحذف.", reply_markup=get_coins_menu())
                return
            text = "➖ اختر رقم العملة المراد حذفها:\n"
            for idx, (coin_id, symbol) in enumerate(coins_list, 1):
                text += f"{idx}. {symbol} (ID: {coin_id})\n"
            text += "\nأرسل رقم المعرف (ID) للحذف."
            await query.edit_message_text(text)
            context.user_data['action'] = 'delete_coin'

    elif data == 'view_coins':
        async with AsyncSessionLocal() as session:
            result = await session.execute(select(TrackedCoin.symbol, TrackedCoin.allocated_capital, TrackedCoin.timeframe, TrackedCoin.added_at))
            coins = result.all()
            if not coins:
                text = "📋 لا توجد عملات مضافة حتى الآن."
            else:
                text = "📋 *قائمة العملات المتابعة (من قاعدة البيانات):*\n\n"
                for sym, cap, tf, date in coins:
                    text += f"🪙 {sym}\n💵 رأس المال: {cap:.2f}\n⏱️ الإطار: {tf}\n📅 تاريخ الإضافة: {date.strftime('%Y-%m-%d')}\n➖➖➖➖➖➖\n"
        await query.edit_message_text(text, reply_markup=get_coins_menu(), parse_mode='Markdown')

    elif data == 'elite_instant_report':
        # ✅ تقرير كامل باستخدام بيانات جدول PaperTrade
        async with AsyncSessionLocal() as session:
            # حالة النظام
            cfg = await session.execute(select(UserConfig.elite_enabled, UserConfig.paper_capital).where(UserConfig.telegram_id == ADMIN_ID))
            cfg_data = cfg.first()
            status_sys = cfg_data[0] if cfg_data else False
            total_capital = cfg_data[1] if cfg_data else 0

            # إحصائيات الصفقات الحقيقية
            total_trades = await session.execute(select(PaperTrade).count())
            win_trades = await session.execute(select(PaperTrade).where(PaperTrade.status == 'WON').count())
            total_pnl = await session.execute(select(func.sum(PaperTrade.pnl)))
            total_pnl = total_pnl.scalar() or 0

            # حساب الدقة
            accuracy = (win_trades.scalar() / total_trades.scalar()) * 100 if total_trades.scalar() > 0 else 0.0

        report_text = (
            "📊 *تقرير الأداء اللحظي (بيانات حقيقية)*\n\n"
            f"⚙️ حالة النظام: {'يعمل 🟢' if status_sys else 'متوقف 🔴'}\n"
            f"💵 رأس المال الأساسي: {total_capital:,.2f} USDT\n"
            f"🪙 عدد العملات المضافة: {await session.scalar(select(TrackedCoin).count())}\n"
            f"📈 إجمالي الصفقات المنفذة: {total_trades.scalar()}\n"
            f"✅ نسبة النجاح: {accuracy:.2f}%\n"
            f"💰 صافي الربح/الخسارة: {total_pnl:,.2f} USDT\n"
            f"🕒 آخر تحديث: {datetime.now().strftime('%H:%M:%S')}"
        )
        await query.edit_message_text(report_text, reply_markup=get_private_trades_menu(), parse_mode='Markdown')

# --- معالج النصوص والأزرار السفلية ---
async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_admin(update):
        return
    if not update.message:
        return
    text = update.message.text.strip()

    # ✅ تنفيذ عملية الحذف
    if context.user_data.get('action') == 'delete_coin':
        try:
            coin_id = int(text)
            async with AsyncSessionLocal() as session:
                await session.execute(delete(TrackedCoin).where(TrackedCoin.id == coin_id))
                await session.commit()
            await update.message.reply_text(f"✅ تم حذف العملة رقم {coin_id} من قاعدة البيانات بنجاح.", reply_markup=get_coins_menu())
        except Exception as e:
            await update.message.reply_text(f"❌ فشل في الحذف: {str(e)}")
        finally:
            context.user_data.pop('action', None)
        return

    # --- ✅ الأسعار الحية: من قاعدة البيانات فقط ---
    if "📈 الأسعار الحية" in text:
        async with AsyncSessionLocal() as session:
            result = await session.execute(select(TrackedCoin.symbol))
            coins_in_db = result.scalars().all()
        if not coins_in_db:
            await update.message.reply_text("❌ لا توجد عملات مضافة.")
            return
        price_text = "📈 *الأسعار الحية (للعملات المضافة لديك فقط)*\n\n"
        for coin_symbol in coins_in_db:
            try:
                yahoo_symbol = coin_symbol.replace("USDT", "-USD")
                ticker = yf.Ticker(yahoo_symbol)
                price = ticker.info.get('regularMarketPrice', 'غير متاح')
                if isinstance(price, float):
                    price_text += f"🪙 {coin_symbol}: {price:,.2f} USDT 📊\n"
                else:
                    price_text += f"🪙 {coin_symbol}: {price} ⚠️\n"
            except:
                price_text += f"🪙 {coin_symbol}: خطأ في جلب السعر ❌\n"
        await update.message.reply_text(price_text, parse_mode='Markdown')

    # --- ✅ تقرير التدريب (يستخدم جدول الصفقات) ---
    elif "🧠 تقرير التدريب والتعلم" in text:
        async with AsyncSessionLocal() as session:
            total = await session.execute(select(PaperTrade).count())
            wins = await session.execute(select(PaperTrade).where(PaperTrade.status == 'WON').count())
            high_conf = await session.execute(select(PaperTrade).where(PaperTrade.confidence > 80).count())
            accuracy = (wins.scalar() / total.scalar()) * 100 if total.scalar() > 0 else 0

        text_report = (
            "🧠 *تقرير التدريب والتعلم الذكي*\n\n"
            f"✅ دقة التنبؤ المحسوبة: {accuracy:.2f}%\n"
            f"📚 عدد الصفقات المحللة: {total.scalar()}\n"
            f"⭐ صفقات بثقة عالية (+80%): {high_conf.scalar()}\n"
            f"🔄 حالة التعلم: نشط ومستمر 🧠"
        )
        await update.message.reply_text(text_report, parse_mode='Markdown')

    # --- ✅ إدارة رأس المال (يقرأ من UserConfig و TrackedCoin) ---
    elif "💰 إدارة رأس المال" in text:
        async with AsyncSessionLocal() as session:
            total_capital = await session.execute(select(func.sum(TrackedCoin.allocated_capital)))
            total_capital = total_capital.scalar() or 0
            cfg = await session.execute(select(UserConfig.risk_level, UserConfig.paper_capital).where(UserConfig.telegram_id == ADMIN_ID))
            cfg_data = cfg.first()
            risk = cfg_data[0] if cfg_data else "medium"
            base_cap = cfg_data[1] if cfg_data else 0

        text_capital = (
            "💰 *إدارة رأس المال (بيانات من قاعدة البيانات)*\n\n"
            f"💵 رأس المال الأساسي: {base_cap:,.2f} USDT\n"
            f"💵 الرصيد المخصص للعملات: {total_capital:,.2f} USDT\n"
            f"⚠️ مستوى المخاطرة المحدد: {risk.upper()}\n"
            f"💸 المخاطرة لكل صفقة: {'1%' if risk=='low' else '1.5%' if risk=='medium' else '2.5%'}"
        )
        await update.message.reply_text(text_capital, parse_mode='Markdown')

    elif "🌟 الصفقات الخاصة" in text:
        await update.message.reply_text("🌟 مركز التحكم:", reply_markup=get_private_trades_menu())
    elif "🌐 إدارة العملات" in text:
        await update.message.reply_text("🪙 إدارة العملات:", reply_markup=get_coins_menu())

    elif "▶️ بدء التعلم الخفي" in text:
        async with AsyncSessionLocal() as session:
            cfg = await session.execute(select(UserConfig).where(UserConfig.telegram_id == ADMIN_ID))
            cfg = cfg.scalars().first()
            if cfg: cfg.is_active = True
            else: session.add(UserConfig(telegram_id=ADMIN_ID, is_active=True))
            await session.commit()
        await update.message.reply_text("🚀 تم تفعيل نظام التعلم. النظام يعمل الآن.")

    elif "⏸️ إيقاف التعلم الخفي" in text:
        async with AsyncSessionLocal() as session:
            cfg = await session.execute(select(UserConfig).where(UserConfig.telegram_id == ADMIN_ID))
            cfg = cfg.scalars().first()
            if cfg: cfg.is_active = False
            await session.commit()
        await update.message.reply_text("⏸️ تم إيقاف المراقبة مؤقتاً.")
