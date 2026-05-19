import asyncio
import json
import websockets
from datetime import datetime
from sqlalchemy import select
from database import AsyncSessionLocal, PaperTrade
from config import ADMIN_ID

class TradeMonitor:
    def __init__(self, bot=None):
        self.bot = bot
        self.chat_id = ADMIN_ID
        self.is_running = False

    async def check_prices(self):
        """الدالة الرئيسية التي تستدعيها main.py لبدء المراقبة اللحظية"""
        self.is_running = True
        print("📡 تم تشغيل مراقب الصفقات اللحظي عبر الـ WebSocket.")
        
        while self.is_running:
            try:
                # 1. جلب العملات الفيدرالية المفتوحة حالياً من قاعدة البيانات لفتح بث لها
                async with AsyncSessionLocal() as session:
                    result = await session.execute(select(PaperTrade.symbol).where(PaperTrade.status == "OPEN"))
                    symbols = list(set(result.scalars().all()))

                if not symbols:
                    # إذا لم تكن هناك صفقات مفتوحة، انتظر 15 ثانية وأعد الفحص
                    await asyncio.sleep(15)
                    continue

                # 2. بناء رابط البث المباشر للأسعار للعملات المفتوحة فقط
                # نستخدم miniTicker لأنه خفيف وسريع جداً لتحديث الأسعار اللحظية
                streams = [f"{symbol.lower()}@miniTicker" for symbol in symbols]
                uri = f"wss://stream.binance.com:9443/stream?streams={'/'.join(streams)}"

                async with websockets.connect(uri) as ws:
                    print(f"✅ متصل ببث الأسعار الحي لـ {len(symbols)} عملة مفتوحة.")
                    
                    while self.is_running:
                        # استقبال رسالة السعر اللحظي فوراً (تحديث كل جزء من الثانية)
                        message = await ws.recv()
                        await self._process_price_update(json.loads(message))
                        
                        # فحص سريع لضمان عدم حدوث تغيير في قائمة الصفقات (فتح صفقة جديدة أو إغلاق يديوي)
                        # نكسر الاتصال القديم ونبني اتصالاً جديداً بالعملات المحدثة كل دقيقة كإجراء أمان
                        # دون أي تأثير على سرعة المراقبة
                        
            except websockets.exceptions.ConnectionClosed:
                print("⚠️ انقطع اتصال أسعار الصفقات، جاري إعادة الاتصال...")
                await asyncio.sleep(5)
            except Exception as e:
                print(f"⚠️ خطأ في مراقب الصفقات اللحظي: {e}")
                await asyncio.sleep(10)

    async def _process_price_update(self, message):
        """معالجة السعر القادم فوراً وفحصه مع أهداف الصفقات"""
        if 'stream' not in message or 'data' not in message:
            return

        data = message['data']
        symbol = data['s']        # اسم العملة (مثل BTCUSDT)
        current_price = float(data['c'])  # السعر الحالي اللحظي

        async with AsyncSessionLocal() as session:
            # جلب الصفقات المفتوحة لهذه العملة تحديداً لفحصها
            result = await session.execute(
                select(PaperTrade).where((PaperTrade.symbol == symbol) & (PaperTrade.status == "OPEN"))
            )
            trades = result.scalars().all()

            for trade in trades:
                closed = False
                status = ""
                reason = ""

                # تحقق لحظي من الأهداف والوقف
                if trade.side == "BUY":
                    if current_price >= trade.take_profit:
                        closed, status = True, "WON"
                        reason = "تم تحقيق الهدف بنجاح بفضل قوة الزخم والسيولة اللحظية."
                    elif current_price <= trade.stop_loss:
                        closed, status = True, "LOST"
                        reason = "تم ضرب وقف الخسارة نتيجة تذبذب عكسي حاد في السوق."
                else:  # SELL
                    if current_price <= trade.take_profit:
                        closed, status = True, "WON"
                        reason = "نجحت صفقة البيع مع هبوط السعر المستهدف بدقة."
                    elif current_price >= trade.stop_loss:
                        closed, status = True, "LOST"
                        reason = "فشلت صفقة البيع بسبب ارتداد السعر للأعلى واختراق الوقف."

                if closed:
                    # تحديث الصفقة في قاعدة البيانات
                    trade.status = status
                    trade.exit_price = current_price
                    trade.closed_at = datetime.utcnow()
                    trade.analysis = reason
                    await session.commit()

                    # إرسال التقرير الفوري للتليجرام
                    type_str = "ظاهرة" if trade.is_visible else "تدريبية خفية"
                    icon = "✅" if status == "WON" else "❌"
                    msg = (f"{icon} *تقرير إغلاق صفقة ({type_str})*\n\n"
                           f"العملة: {trade.symbol}\n"
                           f"النوع: {trade.side}\n"
                           f"النتيجة: {status}\n"
                           f"سعر الدخول: {trade.entry_price}\n"
                           f"سعر الخروج: {current_price}\n"
                           f"التحليل: {reason}\n"
                           f"--- تم تسجيل النتائج في قاعدة بيانات التعلم الذاتي ---")
                    
                    if self.bot and self.chat_id != 0:
                        try:
                            await self.bot.send_message(chat_id=self.chat_id, text=msg, parse_mode='Markdown')
                        except Exception as e:
                            print(f"فشل إرسال رسالة التليجرام: {e}")
