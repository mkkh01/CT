import asyncio
import json
import websockets
from datetime import datetime
from sqlalchemy import select
from database import AsyncSessionLocal, PaperTrade, TrackedCoin, UserConfig
from config import ADMIN_ID

# ✅ استيراد آمن ومتوافق مع ملفاتنا
try:
    from Core.ai_engine import AIEngine
    AI_ENGINE_AVAILABLE = True
except ImportError:
    AIEngine = None
    AI_ENGINE_AVAILABLE = False
    print("ℹ️ [MONITOR V3] تحذير: محرك الذكاء غير متاح، سيتم تعطيل التحليل التلقائي.")


class TradeMonitor:
    def __init__(self, bot=None):
        self.bot = bot
        self.chat_id = ADMIN_ID
        self.is_running = False

    async def check_prices(self):
        # ✅ تهيئة المحرك مرة واحدة فقط
        ai = AIEngine(bot=self.bot, chat_id=self.chat_id) if AI_ENGINE_AVAILABLE and AIEngine else None
        self.is_running = True
        print("📡 تم تشغيل الرادار والمحلل التحليلي V3.2 بنجاح.")
        
        while self.is_running:
            try:
                async with AsyncSessionLocal() as session:
                    # --- 1. فحص نشاط النظام (معدل ليتناسب مع أزرار التحكم) ---
                    cfg_res = await session.execute(select(UserConfig).where(UserConfig.telegram_id == self.chat_id))
                    cfg = cfg_res.scalars().first()
                    
                    # ✅ تعديل هام: إذا لم يكن هناك إعدادات، أو زر النخبة متوقف، نتوقف
                    if not cfg or not cfg.elite_enabled: 
                        await asyncio.sleep(20)
                        continue

                    # --- 2. جولة مسح وتحليل جميع العملات المضافة ---
                    coins_res = await session.execute(select(TrackedCoin))
                    tracked_list = coins_res.scalars().all()
                    
                    for coin in tracked_list:
                        try:
                            if ai: # نفذ فقط إذا كان المحرك متاحاً
                                await ai.analyze_and_trade(coin.symbol, timeframe=coin.timeframe, capital=coin.allocated_capital)
                        except Exception as e:
                            print(f"⚠️ خطأ في تحليل {coin.symbol}: {str(e)}")
                        await asyncio.sleep(0.5) # تسريع قليلاً

                    # --- 3. جلب الصفقات المفتوحة للمراقبة اللحظية ---
                    trades_res = await session.execute(
                        select(PaperTrade).where(PaperTrade.status == "OPEN")
                    )
                    open_trades = trades_res.scalars().all()
                    symbols = list(set([t.symbol for t in open_trades])) # قائمة فريدة

                # --- 4. مراقبة الأسعار مباشرة إذا كانت هناك صفقات مفتوحة ---
                if symbols:
                    streams = [f"{s.lower()}@miniTicker" for s in symbols]
                    uri = f"wss://stream.binance.com:9443/stream?streams={'/'.join(streams)}"
                    
                    try:
                        async with websockets.connect(uri, ping_interval=20, ping_timeout=60) as ws:
                            # مراقبة لمدة 3 دقائق (180 ثانية) قبل العودة للمسح الشامل
                            for _ in range(180):
                                if not self.is_running: break # خروج آمن
                                try:
                                    msg = await asyncio.wait_for(ws.recv(), timeout=5)
                                    await self._process_price_update(json.loads(msg))
                                except asyncio.TimeoutError:
                                    continue
                                except Exception as ws_err:
                                    print(f"🔌 [MONITOR] خطأ في اتصال المراقبة: {ws_err}")
                                    break # اخرج وأعد الاتصال
                                await asyncio.sleep(1)
                    except Exception as conn_err:
                        print(f"🔌 [MONITOR] فشل الاتصال بالمراقبة: {conn_err}")
                        await asyncio.sleep(5)
                else:
                    # لا يوجد صفقات، انتظر قليلاً قبل المسح مجدداً
                    await asyncio.sleep(15)

            except Exception as e:
                print(f"⚠️ [MONITOR] خطأ في الحلقة الرئيسية: {str(e)}")
                await asyncio.sleep(10)

    async def _process_price_update(self, message):
        """معالجة تحديث السعر واتخاذ قرار الإغلاق"""
        if 'data' not in message: return
        data = message['data']
        symbol, current_price = data['s'], float(data['c'])

        async with AsyncSessionLocal() as session:
            # جلب جميع الصفقات المفتوحة لهذه العملة
            res = await session.execute(
                select(PaperTrade).where(
                    (PaperTrade.symbol == symbol) & 
                    (PaperTrade.status == "OPEN")
                )
            )
            
            open_trades_list = res.scalars().all()
            if open_trades_list:
                print(f"👀 [MONITOR] جاري مراقبة {len(open_trades_list)} صفقة مفتوحة لـ {symbol}")

            for trade in open_trades_list:
                closed, status = False, ""

                # --- منطق الإغلاق المطور ---
                if trade.type == "BUY":
                    # شراء: الربح عندما يرتفع السعر، الخسارة عندما ينخفض
                    if trade.take_profit and current_price >= trade.take_profit:
                        closed, status = True, "WON"
                    elif trade.stop_loss and current_price <= trade.stop_loss:
                        closed, status = True, "LOST"

                elif trade.type == "SELL":
                    # بيع (صفقة عكسية): الربح عندما ينخفض السعر، الخسارة عندما يرتفع
                    if trade.take_profit and current_price <= trade.take_profit:
                        closed, status = True, "WON"
                    elif trade.stop_loss and current_price >= trade.stop_loss:
                        closed, status = True, "LOST"

                # --- تنفيذ الإغلاق والحسابات ---
                if closed:
                    reason = self._generate_analysis(trade, status)
                    
                    trade.status = status
                    trade.exit_price = current_price
                    trade.closed_at = datetime.utcnow()
                    trade.result_reason = reason

                    # ✅ حساب دقيق للربح والخسارة بناءً على نوع الصفقة
                    if trade.type == "BUY":
                        pnl_pct = ((current_price - trade.entry_price) / trade.entry_price) * 100
                    else: # SELL
                        pnl_pct = ((trade.entry_price - current_price) / trade.entry_price) * 100
                    
                    trade.pnl = round((trade.amount * pnl_pct) / 100, 4)

                    await session.commit()
                    print(f"💰 [MONITOR] تم إغلاق صفقة {symbol} بنتيجة {status} وربح/خسارة {trade.pnl} USDT")

                    # --- إرسال تقرير النتيجة للتليجرام ---
                    if self.bot:
                        icon = "✅" if status == "WON" else "❌"
                        elite_tag = "🌟 *صفقة نخبة*" if trade.is_elite else "🔬 *سجل تعلم*"
                        
                        report_msg = (
                            f"{icon} {elite_tag} مغلقة\n\n"
                            f"🪙 العملة: #{symbol}\n"
                            f"📈 النوع: {trade.type}\n"
                            f"🏁 النتيجة: {status}\n"
                            f"💵 الدخول: `{trade.entry_price}`\n"
                            f"💵 الخروج: `{current_price}`\n"
                            f"📊 الربح/الخسارة: `{trade.pnl:.2f}%`\n\n"
                            f"🧠 *التحليل العميق:*\n{reason}"
                        )
                        
                        try:
                            await self.bot.send_message(self.chat_id, report_msg, parse_mode='Markdown')
                        except Exception as send_err:
                            print(f"❌ [MONITOR] فشل إرسال تقرير الإغلاق: {send_err}")

    def _generate_analysis(self, trade, status):
        """توليد تفسير منطقي للنتيجة بناءً على البيانات المخزنة"""
        try:
            snapshot = json.loads(trade.technical_snapshot) if trade.technical_snapshot else {}
            rsi = snapshot.get("RSI", "غير محدد")
            macd = snapshot.get("MACD", "غير محدد")
            regime = snapshot.get("MarketRegime", "عادي")
            
            if status == "WON":
                return (
                    f"✅ تحليل ناجح:\n"
                    f"- توافقت الإشارة مع اتجاه السوق ({regime}).\n"
                    f"- مؤشر القوة النسبية (RSI): {rsi} (كان في منطقة آمنة ومشجعة).\n"
                    f"- مؤشر MACD أكد العزم، مما ساعد على الوصول للهدف المحدد."
                )
            else:
                if regime == "STRONG_DOWN":
                    return f"❌ فشل بسبب اتجاه السوق العام: السوق كان في موجة هبوط قوية ({regime}) لم يستطع التحليل الفني الصمود أمامها."
                elif rsi and float(rsi) > 70:
                    return f"❌ فشل نتيجة تشبع شرائي: دخلنا الصفقة بينما المؤشر (RSI={rsi}) في منطقة تشبع، فحدث انعكاس مفاجئ للسعر."
                else:
                    return f"❌ فشل نتيجة تذبذب عالٍ: كسر السعر مستوى الوقف المحدد نتيجة تقلبات سريعة، رغم أن المؤشرات الفنية كانت {macd}."
        except Exception as e:
            return f"تم الإغلاق تلقائياً عند حدود الوقف/الهدف المبرمجة. (تفاصيل تقنية: {str(e)})"
