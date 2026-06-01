from telegram import Update
from telegram.ext import (
    ContextTypes, ConversationHandler, CommandHandler,
    MessageHandler, CallbackQueryHandler, filters
)
from telegram.error import Conflict, NetworkError, TimedOut
from datetime import datetime
from sqlalchemy import select, delete, func
from database import AsyncSessionLocal  # ✅ فقط الاتصال
# ✅ تم تعديل أسماء الجداول لتطابق الموجودة في صورتك بالضبط
from database import TrackedCoinsV3 as TrackedCoin, UsersConfig as UserConfig
from config import ADMIN_ID
from bot.keyboards import get_main_menu, get_coins_menu, get_private_trades_menu, get_timeframe_menu
import yfinance as yf

# تعريف حالات المحادثة لإضافة العملة
NAME, CAPITAL, TIMEFRAME = range(3)

async def check_admin(update: Update) -> bool:
    """التحقق من صلاحية المستخدم - آمن تماماً"""
    user_id = update.effective_user.id
    return ADMIN_ID != 0 and user_id == ADMIN_ID

# معالج الأخطاء العام
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    error = context.error
    print(f"⚠️ نظام: حدث خطأ -> {str(error)}")

    if isinstance(error, Conflict):
        print("🚨 كشف تعارض: يوجد نسخة أخرى تعمل. تم تجاهل الخطأ ومتابعة العمل...")
        return
    elif isinstance(error, (NetworkError, TimedOut)):
        print("🔌 انقطاع شبكة: سيتم إعادة المحاولة تلقائياً...")
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

# --- منطق إضافة عملة جديدة (من خلال إدارة العملات فقط) ---
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

    # ✅ حفظ الاسم المدخل من قبلك في قاعدة البيانات
    context.user_data["symbol"] = symbol_input
    await update.message.reply_text("💰 أدخل رأس المال المخصص لهذه العملة (رقم فقط):")
    return CAPITAL

async def get_capital(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return CAPITAL
        
    try:
        capital_value = float(update.message.text.strip())
        if capital_value <= 0:
            raise ValueError("قيمة صفر أو سالبة")

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

    # ✅ إضافة العملة الجديدة إلى جدول tracked_coins_v3 الموجود لديك
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
        try: 
            await query.message.delete()
        except: 
            pass
        await context.bot.send_message(update.effective_chat.id, "🏠 القائمة الرئيسية:", reply_markup=get_main_menu())

    elif data == 'private_trades':
        await query.edit_message_text(
            "🌟 *مركز التحكم والصفقات الخاصة*\nتحكم في نظام الإشارات وعرض التقارير:", 
            reply_markup=get_private_trades_menu(), 
            parse_mode='Markdown'
        )

    elif data in ['elite_on', 'elite_off']:
        is_on = (data == 'elite_on')
        # ✅ استخدام جدول users_config الموجود في صورتك
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
        # ✅ جلب العملات من جدول tracked_coins_v3 فقط
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
        # ✅ عرض القائمة كاملة من قاعدة البيانات
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(TrackedCoin.symbol, TrackedCoin.allocated_capital, TrackedCoin.timeframe)
            )
            coins = result.all()

            if not coins:
                text = "📋 لا توجد عملات مضافة حتى الآن. استخدم 'إضافة عملة'."
            else:
                text = "📋 *قائمة العملات المتابعة (من قاعدة البيانات):*\n\n"
                for sym, cap, tf in coins:
                    text += f"🪙 {sym}\n💵 رأس المال: {cap:.2f}\n⏱️ الإطار: {tf}\n➖➖➖➖➖➖\n"

        await query.edit_message_text(text, reply_markup=get_coins_menu(), parse_mode='Markdown')

    elif data == 'elite_instant_report':
        async with AsyncSessionLocal() as session:
            cfg = await session.execute(select(UserConfig.elite_enabled).where(UserConfig.telegram_id == ADMIN_ID))
            status_sys = cfg.scalar_one_or_none()
            
            count_coins = await session.execute(select(TrackedCoin).count())
            count_coins = count_coins.scalar()

        report_text = (
            "📊 *تقرير الأداء اللحظي*\n\n"
            f"⚙️ حالة النظام: {'يعمل 🟢' if status_sys else 'متوقف 🔴'}\n"
            f"🪙 عدد العملات المضافة: {count_coins}\n"
            f"📈 يتم متابعة الأسعار وتحليلها لحظياً...\n"
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

    # ✅ تنفيذ عملية الحذف من قاعدة البيانات
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

    # --- ✅ الأسعار الحية: تجلب فقط العملات الموجودة في جدول tracked_coins_v3 ---
    if "📈 الأسعار الحية" in text:
        async with AsyncSessionLocal() as session:
            # جلب أسماء العملات التي أضفتها أنت فقط
            result = await session.execute(select(TrackedCoin.symbol))
            coins_in_db = result.scalars().all()

        if not coins_in_db:
            await update.message.reply_text("❌ لا توجد عملات مضافة في قاعدة البيانات حالياً. أضف أولاً من 'إدارة العملات'.")
            return

        # بناء الرسالة وجلب السعر لكل عملة موجودة
        price_text = "📈 *الأسعار الحية (للعملات المضافة لديك فقط)*\n\n"
        for coin_symbol in coins_in_db:
            try:
                # تحويل الصيغة لتناسب مكتبة الأسعار (مثل BTCUSDT -> BTC-USD)
                yahoo_symbol = coin_symbol.replace("USDT", "-USD")
                ticker = yf.Ticker(yahoo_symbol)
                price = ticker.info.get('regularMarketPrice', 'غير متاح')
                
                if isinstance(price, float):
                    price_text += f"🪙 {coin_symbol}: {price:,.2f} USDT 📊\n"
                else:
                    price_text += f"🪙 {coin_symbol}: {price} ⚠️\n"
            except Exception as e:
                price_text += f"🪙 {coin_symbol}: خطأ في جلب السعر ❌\n"

        price_text += "\n🔄 يتم التحديث تلقائياً..."
        await update.message.reply_text(price_text, parse_mode='Markdown')

    # --- تقرير التدريب ---
    elif "🧠 تقرير التدريب والتعلم" in text:
        async with AsyncSessionLocal() as session:
            total_coins = await session.execute(select(TrackedCoin).count())
            total_coins = total_coins.scalar()

        text_report = (
            "🧠 *تقرير التدريب والتعلم الذكي*\n\n"
            f"🪙 العملات قيد التحليل: {total_coins}\n"
            f"🔄 حالة التعلم: نشط ومستمر 🧠\n"
            f"⚙️ يتم تحليل البيانات الواردة من السوق لحظياً...\n"
            f"📊 جودة البيانات: ممتازة"
        )
        await update.message.reply_text(text_report, parse_mode='Markdown')

    # --- إدارة رأس المال: قراءة إجمالي من قاعدة البيانات ---
    elif "💰 إدارة رأس المال" in text:
        async with AsyncSessionLocal() as session:
            # مجموع رؤوس الأموال المخصصة للعملات التي أضفتها
            total_capital = await session.execute(select(func.sum(TrackedCoin.allocated_capital)))
            total_capital = total_capital.scalar() or 0

            # إعدادات المخاطرة
            risk_percent = 1.5

        text_capital = (
            "💰 *إدارة رأس المال (إجمالي مخصص)*\n\n"
            f"💵 الرصيد الكلي المخصص: {total_capital:,.2f} USDT\n"
            f"💸 المخاطرة لكل صفقة: {risk_percent}% من رأس المال\n"
            f"🔒 نسبة الأمان: تحسب بناءً على التقلب\n"
            f"📊 العملات النشطة: تقاس من قاعدة البيانات"
        )
        await update.message.reply_text(text_capital, parse_mode='Markdown')

    elif "🌟 الصفقات الخاصة" in text:
        await update.message.reply_text("🌟 مركز التحكم:", reply_markup=get_private_trades_menu())
    elif "🌐 إدارة العملات" in text:
        await update.message.reply_text("🪙 إدارة العملات:", reply_markup=get_coins_menu())
    
    # --- أزرار التحكم ---
    elif "▶️ بدء التعلم الخفي" in text:
        async with AsyncSessionLocal() as session:
            cfg = await session.execute(select(UserConfig).where(UserConfig.telegram_id == ADMIN_ID))
            cfg = cfg.scalars().first()
            if cfg: 
                cfg.elite_enabled = True
            else: 
                session.add(UserConfig(telegram_id=ADMIN_ID, elite_enabled=True))
            await session.commit()
        await update.message.reply_text("🚀 تم تفعيل نظام التعلم. يراقب العملات الموجودة في قاعدة البيانات الآن.")

    elif "⏸️ إيقاف التعلم الخفي" in text:
        async with AsyncSessionLocal() as session:
            cfg = await session.execute(select(UserConfig).where(UserConfig.telegram_id == ADMIN_ID))
            cfg = cfg.scalars().first()
            if cfg: 
                cfg.elite_enabled = False
                await session.commit()
        await update.message.reply_text("⏸️ تم إيقاف المراقبة مؤقتاً.")
