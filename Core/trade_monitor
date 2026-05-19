import asyncio
import requests
from datetime import datetime
from sqlalchemy import select, update
from database import AsyncSessionLocal, PaperTrade
from config import ADMIN_ID

class TradeMonitor:
    def __init__(self, bot=None):
        self.bot = bot
        self.chat_id = ADMIN_ID

    async def check_prices(self):
        """مراقبة أسعار الصفقات المفتوحة وإغلاقها عند لمس الهدف أو الوقف"""
        while True:
            try:
                async with AsyncSessionLocal() as session:
                    # جلب الصفقات المفتوحة فقط
                    result = await session.execute(select(PaperTrade).where(PaperTrade.status == "OPEN"))
                    open_trades = result.scalars().all()

                    if not open_trades:
                        await asyncio.sleep(60) # انتظر دقيقة إذا لم تكن هناك صفقات
                        continue

                    # جلب الأسعار الحية من باينانس لجميع العملات المطلوبة دفعة واحدة
                    symbols = list(set([t.symbol for t in open_trades]))
                    url = 'https://api.binance.com/api/v3/ticker/price'
                    res = requests.get(url).json()
                    prices = {item['symbol']: float(item['price']) for item in res if item['symbol'] in symbols}

                    for trade in open_trades:
                        current_price = prices.get(trade.symbol)
                        if not current_price: continue

                        closed = False
                        status = ""
                        reason = ""

                        # تحقق من الهدف والوقف
                        if trade.side == "BUY":
                            if current_price >= trade.take_profit:
                                closed, status = True, "WON"
                                reason = "تم تحقيق الهدف بفضل قوة الزخم والسيولة."
                            elif current_price <= trade.stop_loss:
                                closed, status = True, "LOST"
                                reason = "تم ضرب وقف الخسارة نتيجة تذبذب عكسي أو ضعف السيولة."
                        else: # SELL
                            if current_price <= trade.take_profit:
                                closed, status = True, "WON"
                                reason = "نجحت صفقة البيع مع انخفاض السعر كما كان متوقعاً."
                            elif current_price >= trade.stop_loss:
                                closed, status = True, "LOST"
                                reason = "فشلت صفقة البيع بسبب ارتداد السعر للأعلى."

                        if closed:
                            trade.status = status
                            trade.exit_price = current_price
                            trade.closed_at = datetime.utcnow()
                            trade.analysis = reason
                            await session.commit()

                            # إرسال تقرير للمستخدم (سواء كانت الصفقة ظاهرة أو خفية)
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
                                except: pass

                await asyncio.sleep(10) # فحص كل 10 ثوانٍ
            except Exception as e:
                print(f"⚠️ خطأ في مراقب الصفقات: {e}")
                await asyncio.sleep(30)
