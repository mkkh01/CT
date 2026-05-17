from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import Application, CommandHandler, ContextTypes
from config import Config
from database import SessionLocal, User, Watchlist, StrategyStat
from logger import setup_logger

logger = setup_logger("TelegramBot")

class TelegramBot:
    def __init__(self):
        # بناء تطبيق التلغرام باستخدام التوكن الثابت في ملف الإعدادات
        self.application = Application.builder().token(Config.TELEGRAM_TOKEN).build()
        self._register_handlers()

    def _register_handlers(self):
        """تسجيل الأوامر البرمجية المتاحة داخل البوت"""
        self.application.add_handler(CommandHandler("start", self.start_command))
        self.application.add_handler(CommandHandler("status", self.status_command))
        self.application.add_handler(CommandHandler("stats", self.stats_command))

    def _is_admin(self, user_id: int) -> bool:
        """جدار حماية صارم للتحقق من أن المستخدم هو صاحب البوت الحقيقي"""
        return user_id == Config.ADMIN_ID

    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """أمر الترحيب وتأسيس لوحة التحكم بالأزرار"""
        user_id = update.effective_user.id
        
        if not self._is_admin(user_id):
            await update.message.reply_text("🛑 خطأ حماية: ليس لديك صلاحية الوصول إلى هذا النظام!")
            logger.warning(f"🔒 محاولة دخول غير مصرح بها من الـ ID: {user_id}")
            return

        # لوحة تحكم مريحة تظهر كأزرار أسفل شاشة التلغرام
        keyboard = [['/status', '/stats']]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

        welcome_msg = (
            "🤖 **أهلاً بك في نظام الـ Copilot الخوارزمي المتقدم!**\n\n"
            "لوحة التحكم جاهزة ومؤمنة بالكامل لحسابك الخاص.\n"
            "استخدم الأزرار بالأسفل لاستعراض حالة السوق الحية أو التقارير الإحصائية."
        )
        await update.message.reply_text(welcome_msg, reply_markup=reply_markup, parse_mode="Markdown")

    async def status_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """عرض حالة النظام الحالية وقائمة العملات التي يتم فحصها حياً"""
        user_id = update.effective_user.id
        if not self._is_admin(user_id):
            return

        db = SessionLocal()
        try:
            # جلب العملات النشطة في قائمة المراقبة
            active_symbols = db.query(Watchlist).filter(Watchlist.enabled == True).all()
            symbols_list = [item.symbol for item in active_symbols]
            
            status_msg = (
                "⚙️ **حالة النظام الحالية:**\n\n"
                f"🟢 **الحالة:** يعمل بكفاءة العالية\n"
                f"📊 **قائمة المراقبة النشطة ({len(symbols_list)}):**\n"
                f"`{', '.join(symbols_list) if symbols_list else 'فارغة'}`\n\n"
                f"🛡️ **مستوى المخاطرة الافتراضي:** `CONSERVATIVE (1%)`"
            )
            await update.message.reply_text(status_msg, parse_mode="Markdown")
        except Exception as e:
            logger.error(f"خطأ أثناء جلب حالة النظام للبوت: {str(e)}")
            await update.message.reply_text("❌ حدث خطأ غير متوقع أثناء قراءة البيانات.")
        finally:
            db.close()

    async def stats_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """توليد تقرير إحصائي حي من قاعدة البيانات يوضح أداء الاستراتيجيات الثلاث"""
        user_id = update.effective_user.id
        if not self._is_admin(user_id):
            return

        db = SessionLocal()
        try:
            stats = db.query(StrategyStat).all()
            
            if not stats:
                await update.message.reply_text("📊 لا توجد إحصائيات تراكمية مسجلة حتى الآن. في انتظار إغلاق صفقات الظل الأولى.")
                return

            report = "📈 **تقرير الأداء الإحصائي للاستراتيجيات (Shadow Learning):**\n\n"
            for stat in stats:
                report += (
                    f"🎯 **الاستراتيجية:** `{stat.strategy_name}`\n"
                    f"🔄 إجمالي الصفقات: {stat.total_trades}\n"
                    f"✅ عدد الرابحة: {stat.wins} | ❌ عدد الخاسرة: {stat.losses}\n"
                    f"⚖️ متوسط الـ R:R المحقق: `{stat.avg_rr:.2f}`\n"
                    f"📊 عامل الربحية (Profit Factor): `{stat.profit_factor:.2f}`\n"
                    f"🕒 آخر تحديث: {stat.updated_at.strftime('%Y-%m-%d %H:%M')}\n"
                    f"-----------------------------------\n"
                )
            await update.message.reply_text(report, parse_mode="Markdown")
        except Exception as e:
            logger.error(f"خطأ أثناء توليد التقرير الإحصائي للبوت: {str(e)}")
            await update.message.reply_text("❌ فشل توليد التقرير الإحصائي حالياً.")
        finally:
            db.close()

    async def send_signal_alert(self, signal_data: dict):
        """دالة خاصة لإرسال إشارات التداول الفورية الحية إلى حسابك على التلغرام مباشرة"""
        try:
            # صياغة رسالة الإشارة بتنسيق تجميلي احترافي يسهل قراءته بنظرة واحدة
            direction_emoji = "🟢 LONG / BUY" if signal_data['direction'] == "BUY" else "🔴 SHORT / SELL"
            
            message = (
                f"🚨 **إشارة تداول خوارزمية جديدة!**\n\n"
                f"🪙 **العملة:** #{signal_data['symbol'].replace('/', '')} | `{signal_data['symbol']}`\n"
                f"📈 **الاتجاه:** {direction_emoji}\n"
                f"🛠️ **الاستراتيجية:** `{signal_data['strategy']}`\n"
                f"📊 **معامل الثقة:** `{signal_data['confidence']:.1f}%` 🌟\n\n"
                f"📍 **سعر الدخول:** `{signal_data['entry']:.6f}`\n"
                f"🎯 **الهدف (TP):** `{signal_data['tp']:.6f}`\n"
                f"🛑 **وقف الخسارة (SL):** `{signal_data['sl']:.6f}`\n\n"
                f"⚖️ **معدل الـ R:R:** `{signal_data['rr']:.2f}`\n"
                f"⚙️ **بيئة السوق:** `{signal_data['regime']}`\n"
                f"💰 **الحجم المقترح للمركز:** `{signal_data['position_size']:.4f}` وحدات"
            )
            # إرسال الرسالة إلى الـ ADMIN_ID الخاص بك مباشرة
            await self.application.bot.send_message(chat_id=Config.ADMIN_ID, text=message, parse_mode="Markdown")
            logger.info(f"✨ [إشعار تلغرام] تم إرسال إشارة {signal_data['symbol']} بنجاح إلى الأدمن.")
        except Exception as e:
            logger.error(f"فشل إرسال إشعار الإشارة عبر التلغرام: {str(e)}")
