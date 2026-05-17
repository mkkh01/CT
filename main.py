import asyncio
from datetime import datetime
from config import Config
from database import init_db, SessionLocal, Watchlist, Signal
from exchange_manager import ExchangeManager
from market_regime import MarketRegimeDetector
from analyzer import MultiTimeframeAnalyzer
from strategy_engine import StrategyEngine
from signal_filter import SignalFilter
from scoring_engine import ScoringEngine
from risk_manager import RiskManager
from shadow_learning_engine import ShadowLearningEngine
from telegram_bot import TelegramBot
from logger import setup_logger

logger = setup_logger("MainOrchestrator")

async def main():
    logger.info("🚀 جاري بدء تشغيل نظام Copilot الخوارزمي المتقدم...")
    
    # 1. تهيئة وبناء جداول قاعدة البيانات وبذر البيانات الأولية تلقائياً
    init_db()
    logger.info("✅ تم التحقق من سلامة وبناء جداول قاعدة البيانات على Render.")
    
    # 2. استنساخ كائنات المدراء (المنصات، البوت، والتعلم الإحصائي)
    exchange_mgr = ExchangeManager()
    bot = TelegramBot()
    
    # تشغيل بوت التلغرام ليعمل في الخلفية ويستقبل أوامرك دون حظر الحلقة الرئيسية
    await bot.application.initialize()
    await bot.application.start()
    await bot.application.updater.start_polling()
    logger.info("🤖 بوت التلغرام نشط الآن ويستمع للأوامر البرمجية حياً.")

    logger.info("⚡ تم الدخول في حلقة الفحص والتحليل اللانهائية الديناميكية...")
    
    try:
        while True:
            current_time = datetime.utcnow()
            db = SessionLocal()
            
            try:
                # أ. جلب العملات المفعلة في قائمة المراقبة من قاعدة البيانات
                watchlist_items = db.query(Watchlist).filter(Watchlist.enabled == True).all()
                symbols = [item.symbol for item in watchlist_items]
                
                if not symbols:
                    logger.warning("⚠️ قائمة المراقبة فارغة حالياً. جاري الانتظار دورة أخرى...")
                    await asyncio.sleep(60)
                    continue

                # قاموس داخلي لحفظ الأسعار اللحظية الحالية لتغذية محرك صفقات الظل
                current_market_prices = {}

                # ب. فحص العملات عملة تلو الأخرى (Sequential Asset Scanning)
                for symbol in symbols:
                    logger.info(f"🔍 جاري فحص وتحليل الزوج اللحظي: {symbol}...")
                    
                    # 1. جلب بيانات الشموع للأطر الثلاثة بالتوازي من خلال مدير المنصات
                    candles_5m = await exchange_mgr.fetch_candles(symbol, timeframe='5m', limit=100)
                    candles_15m = await exchange_mgr.fetch_candles(symbol, timeframe='15m', limit=100)
                    candles_1h = await exchange_mgr.fetch_candles(symbol, timeframe='1h', limit=100)
                    
                    if not candles_5m or not candles_15m or not candles_1h:
                        continue # تخطي في حال فشل جلب البيانات الفنية
                        
                    # حفظ السعر اللحظي الحالي الأحدث للعملة
                    latest_price = float(candles_5m[-1][4]) # سعر إغلاق الشمعة الأخيرة
                    current_market_prices[symbol] = latest_price

                    # 2. معالجة المؤشرات متعددة الأطر الزمنية
                    mtf_data = MultiTimeframeAnalyzer.analyze(candles_5m, candles_15m, candles_1h)
                    if not mtf_data:
                        continue

                    # 3. تحديد بيئة وحالة السوق الحالية (Market Regime)
                    # نستخدم إطار الـ 15 دقيقة كمعيار أساسي لتحديد نبض وحالة حركة الزوج
                    df_for_regime = MultiTimeframeAnalyzer._prepare_dataframe(candles_15m)
                    regime_data = MarketRegimeDetector.detect(df_for_regime)
                    
                    logger.info(f"📊 حالة السوق الحالية للزوج {symbol}: {regime_data['regime']} | التقلب: {regime_data['volatility']:.2f}%")

                    # 4. استدعاء وتقييم الاستراتيجيات الثلاث بالتوازي
                    setups = [
                        StrategyEngine.evaluate_trend_continuation(mtf_data, regime_data),
                        StrategyEngine.evaluate_breakout(mtf_data, regime_data),
                        StrategyEngine.evaluate_range_reversal(mtf_data, regime_data)
                    ]

                    # 5. معالجة الصفقات المتولدة وعرضها على الفلاتر ومحركات التقييم
                    for setup in setups:
                        if setup.get("decision") == "NO_TRADE":
                            continue
                            
                        # تزويد السيت اب بالعملة المستهدفة
                        setup["symbol"] = symbol
                        
                        # أ- تمرير الصفقة عبر الفلتر الصارم
                        if not SignalFilter.filter(setup, regime_data):
                            continue
                            
                        # ب- حساب معامل وثقة الإشارة رقمياً
                        confidence = ScoringEngine.calculate_score(setup, regime_data, mtf_data)
                        if confidence < Config.MIN_CONFIDENCE_SCORE:
                            logger.info(f"🛑 [رفض] إسقاط صفقة {symbol} لأن معامل ثقتها {confidence:.1f}% أقل من الحد المطلوب {Config.MIN_CONFIDENCE_SCORE}%.")
                            continue
                            
                        # ج- تمرير البيانات لإدارة المخاطر لحساب حجم المركز التداولي
                        # جلب إعدادات حساب الأدمن الأساسي من قاعدة البيانات
                        admin_user = db.query(User).filter(User.user_id == Config.ADMIN_ID).first()
                        capital = admin_user.capital if admin_user else 1000.0
                        risk_lvl = admin_user.risk_level if admin_user else "CONSERVATIVE"
                        
                        pos_size = RiskManager.calculate_position_size(capital, risk_lvl, setup['entry'], setup['sl'])
                        if pos_size <= 0:
                            continue

                        # د- التحقق من شرط التهدئة (Cooldown) لمنع توالي الإشارات السريع
                        last_sig = db.query(Signal).order_by(Signal.created_at.desc()).first()
                        last_time = last_sig.created_at if last_sig else None
                        if not RiskManager.enforce_cooldown(last_time, current_time):
                            continue

                        # 🏁 إذا وصلت الصفقة إلى هنا، فهي صفقة ذهبية معتمدة 100%
                        # أولاً: تسجيل الإشارة رسمياً في قاعدة بيانات الـ Postgres
                        final_signal = Signal(
                            symbol=symbol, direction=setup['decision'], entry=setup['entry'],
                            sl=setup['sl'], tp=setup['tp'], confidence=confidence,
                            strategy=setup['name'], regime=regime_data['regime'], result="PENDING"
                        )
                        db.add(final_signal)
                        db.commit()

                        # ثانياً: تشغيل محاكي الظل لفتح صفقة موازية مخفية لغرض التعلم
                        ShadowLearningEngine.open_shadow_trade(db, setup, regime_data)

                        # ثالثاً: إرسال التنبيه الفوري التجميلي المدعم بكافة التفاصيل لملفك الشخصي بالتلغرام
                        setup['confidence'] = confidence
                        setup['position_size'] = pos_size
                        setup['regime'] = regime_data['regime']
                        await bot.application.bot.loop.create_task(bot.send_signal_alert(setup))

                # 6. تحديث صفقات الظل الحية المفتوحة مسبقاً بناءً على الأسعار اللحظية الجديدة
                if current_market_prices:
                    ShadowLearningEngine.update_live_shadow_trades(db, current_market_prices)

            except Exception as e:
                logger.error(f"🔴 خطأ أثناء تنفيذ الدورة الحالية في المحرك: {str(e)}")
            finally:
                db.close() # إغلاق آمن وحتمي للجلسة لمنع تسريب الاتصالات على Render
            
            # دورة الفحص تعمل بشكل قياسي منظم كل 60 ثانية (دقيقة واحدة)
            await asyncio.sleep(60)

    except (KeyboardInterrupt, SystemExit):
        logger.info("🛑 تم استلام أمر إيقاف النظام يدوياً...")
    finally:
        # الإغلاق النظيف والآمن لكافة اتصالات ومحركات البوت والمنصات قبل إغلاق الخادم
        await exchange_mgr.close_connections()
        await bot.application.updater.stop()
        await bot.application.stop()
        await bot.application.shutdown()
        logger.info("👋 تم إيقاف كافة العمليات والخوادم بنجاح ونظافة تامة.")

if __name__ == "__main__":
    # بدء تشغيل التطبيق بالكامل داخل بيئة الـ Asyncio الحية
    asyncio.run(main())
