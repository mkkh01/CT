from telegram import Update
import asyncio
from telegram.ext import (
    ContextTypes, ConversationHandler, CommandHandler,
    MessageHandler, CallbackQueryHandler, filters
)
from telegram.error import Conflict, NetworkError, TimedOut
from datetime import datetime
from sqlalchemy import select, delete, func
from config import ADMIN_ID
from database import AsyncSessionLocal, TrackedCoin, UserConfig, PaperTrade
from bot.keyboards import get_main_menu, get_coins_menu, get_private_trades_menu, get_timeframe_menu, get_capital_management_menu
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
        await query.edit_message_text("✍️ أرسل رمز العملة (مثل: BTCUSDT):")
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

    elif data == 'edit_base_capital':
        print(f"💰 [CAPITAL] المستخدم {update.effective_user.id} بدأ تعديل رأس المال الأساسي")
        await query.edit_message_text("✍️ أرسل القيمة الجديدة لرأس المال الأساسي (رقم فقط):")
        context.user_data['action'] = 'update_base_capital'

    elif data.startswith('risk_'):
        new_risk = data.replace('risk_', '')
        print(f"⚠️ [RISK] طلب تغيير مستوى المخاطرة إلى: {new_risk}")
        async with AsyncSessionLocal() as session:
            res = await session.execute(select(UserConfig).where(UserConfig.telegram_id == ADMIN_ID))
            cfg = res.scalars().first()
            if cfg:
                cfg.risk_level = new_risk
                await session.commit()
                print(f"✅ [RISK] تم تحديث مستوى المخاطرة بنجاح إلى {new_risk}")
                await query.edit_message_text(f"✅ تم تحديث مستوى المخاطرة إلى: *{new_risk.upper()}*", parse_mode='Markdown')
            else:
                print(f"❌ [RISK] لم يتم العثور على إعدادات للمستخدم {ADMIN_ID}")
                await query.edit_message_text("❌ خطأ: لم يتم العثور على إعدادات المستخدم.")

    elif data == 'elite_instant_report':
        async with AsyncSessionLocal() as session:
            cfg = await session.execute(select(UserConfig.elite_enabled, UserConfig.paper_capital).where(UserConfig.telegram_id == ADMIN_ID))
            cfg_data = cfg.first()
            status_sys = cfg_data[0] if cfg_data else False
            total_capital = cfg_data[1] if cfg_data else 0

            total_trades = await session.scalar(select(func.count(PaperTrade.id))) or 0
            win_trades = await session.scalar(select(func.count(PaperTrade.id)).where(PaperTrade.status == 'WON')) or 0
            total_pnl = await session.scalar(select(func.sum(PaperTrade.pnl))) or 0.0
            count_coins = await session.scalar(select(func.count(TrackedCoin.id))) or 0

            if total_trades == 0:
                accuracy = 0.0
                note = "📌 ملاحظة: لا توجد صفقات منفذة حتى الآن لحساب الدقة."
            else:
                accuracy = (win_trades / total_trades) * 100
                note = ""

        report_text = (
            "📊 *تقرير الأداء اللحظي (بيانات حقيقية)*\n\n"
            f"⚙️ حالة النظام: {'يعمل 🟢' if status_sys else 'متوقف 🔴'}\n"
            f"💵 رأس المال الأساسي: {total_capital:,.2f} USDT\n"
            f"🪙 عدد العملات المضافة: {count_coins}\n"
            f"📈 إجمالي الصفقات المنفذة: {total_trades}\n"
            f"✅ نسبة النجاح: {accuracy:.2f}%\n"
            f"💰 صافي الربح/الخسارة: {total_pnl:,.2f} USDT\n"
            f"{note}\n"
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

    if context.user_data.get('action') == 'update_base_capital':
        try:
            new_val = float(text)
            if new_val < 0: raise ValueError
            print(f"💰 [CAPITAL] جاري تحديث رأس المال الأساسي إلى: {new_val}")
            async with AsyncSessionLocal() as session:
                res = await session.execute(select(UserConfig).where(UserConfig.telegram_id == ADMIN_ID))
                cfg = res.scalars().first()
                if cfg:
                    cfg.paper_capital = new_val
                else:
                    cfg = UserConfig(telegram_id=ADMIN_ID, paper_capital=new_val)
                    session.add(cfg)
                await session.commit()
            print(f"✅ [CAPITAL] تم التحديث بنجاح.")
            await update.message.reply_text(f"✅ تم تحديث رأس المال الأساسي إلى: `{new_val:,.2f} USDT`", parse_mode='Markdown')
        except Exception as e:
            print(f"❌ [CAPITAL] فشل التحديث: {str(e)}")
            await update.message.reply_text("⚠️ قيمة غير صالحة! أدخل رقماً موجباً.")
        finally:
            context.user_data.pop('action', None)
        return

    # --- ✅ الأسعار الحية: تم التحديث لاستخدام WebSocket لتجنب الحظر (Bans) وضمان السرعة القصوى ---
    if "📈 الأسعار الحية" in text:
        print(f"📊 [LIVE PRICES] طلب جلب الأسعار من المستخدم {update.effective_user.id}")
        async with AsyncSessionLocal() as session:
            result = await session.execute(select(TrackedCoin.symbol))
            coins_in_db = result.scalars().all()
        
        if not coins_in_db:
            print("⚠️ [LIVE PRICES] لا توجد عملات مضافة في قاعدة البيانات.")
            await update.message.reply_text("❌ لا توجد عملات مضافة لمتابعة أسعارها.")
            return

        import websockets
        import json
        
        price_text = "📈 *الأسعار الحية (عبر WebSocket)*\n\n"
        streams = [f"{s.lower()}@miniTicker" for s in coins_in_db]
        uri = f"wss://stream.binance.com:9443/stream?streams={'/'.join(streams)}"
        
        waiting_msg = await update.message.reply_text("⏳ جاري الاتصال بـ Binance وجلب الأسعار اللحظية...")
        
        prices_data = {}
        try:
            async with websockets.connect(uri) as ws:
                # ننتظر قليلاً لجمع التحديثات لجميع العملات المطلوبة
                start_time = datetime.now()
                while len(prices_data) < len(coins_in_db) and (datetime.now() - start_time).seconds < 5:
                    msg = await asyncio.wait_for(ws.recv(), timeout=2)
                    data = json.loads(msg)['data']
                    sym = data['s']
                    prices_data[sym] = {
                        'price': float(data['c']),
                        'open': float(data['o'])
                    }
            
            for symbol in coins_in_db:
                if symbol in prices_data:
                    p = prices_data[symbol]['price']
                    o = prices_data[symbol]['open']
                    change = ((p - o) / o) * 100
                    icon = "🟢" if change >= 0 else "🔴"
                    price_text += f"🪙 *{symbol}*: `{p:,.4f}` USDT ({icon} {change:+.2f}%)\n"
                else:
                    price_text += f"🪙 *{symbol}*: ⚠️ لا توجد بيانات (حاول مرة أخرى)\n"
            
            print(f"✅ [LIVE PRICES] تم جلب {len(prices_data)} سعر بنجاح.")
            await waiting_msg.delete()
            await update.message.reply_text(price_text, parse_mode='Markdown')
            
        except Exception as e:
            print(f"❌ [LIVE PRICES] خطأ في WebSocket: {str(e)}")
            await waiting_msg.edit_text(f"⚠️ خطأ في جلب الأسعار: {str(e)}\n\n_ملاحظة: قد يكون هناك حظر مؤقت على الـ IP، يرجى المحاولة لاحقاً._")

    # --- ✅ تقرير التدريب: مُصحح ويعالج الجداول الفارغة ---
    elif "🧠 تقرير التدريب والتعلم" in text:
        async with AsyncSessionLocal() as session:
            total = await session.scalar(select(func.count(PaperTrade.id))) or 0
            wins = await session.scalar(select(func.count(PaperTrade.id)).where(PaperTrade.status == 'WON')) or 0
            high_conf = await session.scalar(select(func.count(PaperTrade.id)).where(PaperTrade.confidence > 80)) or 0

            if total == 0:
                text_report = (
                    "🧠 *تقرير التدريب والتعلم الذكي*\n\n"
                    "📊 النظام جاهز ويعمل بكفاءة.\n"
                    "📌 لم يتم تسجيل أي صفقات حتى الآن، لذا لا توجد بيانات تحليلية لعرضها.\n"
                    "🔄 بمجرد بدء التداول، سيتم حساب الدقة والكفاءة تلقائياً."
                )
            else:
                accuracy = (wins / total) * 100
                text_report = (
                    "🧠 *تقرير التدريب والتعلم الذكي*\n\n"
                    f"✅ دقة التنبؤ المحسوبة: {accuracy:.2f}%\n"
                    f"📚 عدد الصفقات المحللة: {total}\n"
                    f"⭐ صفقات بثقة عالية (+80%): {high_conf}\n"
                    f"🔄 حالة التعلم: نشط ومستمر 🧠"
                )

        await update.message.reply_text(text_report, parse_mode='Markdown')

    # --- ✅ إدارة رأس المال: تم جعلها ديناميكية بالكامل ---
    elif "💰 إدارة رأس المال" in text:
        async with AsyncSessionLocal() as session:
            total_capital = await session.scalar(select(func.sum(TrackedCoin.allocated_capital))) or 0
            cfg = await session.execute(select(UserConfig.risk_level, UserConfig.paper_capital).where(UserConfig.telegram_id == ADMIN_ID))
            cfg_data = cfg.first()
            risk = cfg_data[0] if cfg_data else "medium"
            base_cap = cfg_data[1] if cfg_data else 0

        text_capital = (
            "💰 *إدارة رأس المال (بيانات من قاعدة البيانات)*\n\n"
            f"💵 رأس المال الأساسي: `{base_cap:,.2f}` USDT\n"
            f"💵 الرصيد المخصص للعملات: `{total_capital:,.2f}` USDT\n"
            f"⚠️ مستوى المخاطرة الحالي: *{risk.upper()}*\n"
            f"💸 المخاطرة لكل صفقة: *{'1%' if risk=='low' else '1.5%' if risk=='medium' else '2.5%'}*\n\n"
            "يمكنك تعديل رأس المال الأساسي أو تغيير مستوى المخاطرة من الأزرار أدناه:"
        )
        await update.message.reply_text(text_capital, reply_markup=get_capital_management_menu(), parse_mode='Markdown')

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
