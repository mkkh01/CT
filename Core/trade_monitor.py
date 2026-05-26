import asyncio
import json
import websockets
from datetime import datetime
from sqlalchemy import select
from database import AsyncSessionLocal, PaperTrade, TrackedCoin, UserConfig
from config import ADMIN_ID

class TradeMonitor:
    def __init__(self, bot=None):
        self.bot = bot
        self.chat_id = ADMIN_ID
        self.is_running = False

    async def check_prices(self):
        from Core.ai_engine import AIEngine
        ai = AIEngine(bot=self.bot, chat_id=self.chat_id)
        self.is_running = True
        print("📡 تم تشغيل الرادار والمحلل التحليلي V3.2 بنجاح.")
        
        while self.is_running:
            try:
                async with AsyncSessionLocal() as session:
                    # 1. فحص نشاط النظام
                    cfg_res = await session.execute(select(UserConfig).where(UserConfig.telegram_id == self.chat_id))
                    cfg = cfg_res.scalars().first()
                    if not cfg or not cfg.is_active:
                        await asyncio.sleep(20)
                        continue

                    # 2. جولة صيد الصفقات (Scan)
                    coins_res = await session.execute(select(TrackedCoin))
                    tracked_list = coins_res.scalars().all()
                    
                    for coin in tracked_list:
                        try:
                            await ai.analyze_and_trade(coin.symbol)
                        except Exception as e:
                            print(f"⚠️ خطأ في تحليل {coin.symbol}: {e}")
                        await asyncio.sleep(1)

                    # 3. جلب الصفقات المفتوحة للمراقبة اللحظية
                    trades_res = await session.execute(select(PaperTrade).where(PaperTrade.status == "OPEN"))
                    open_trades = trades_res.scalars().all()
                    symbols = list(set([t.symbol for t in open_trades]))

                if symbols:
                    streams = [f"{s.lower()}@miniTicker" for s in symbols]
                    uri = f"wss://stream.binance.com:9443/stream?streams={'/'.join(streams)}"
                    async with websockets.connect(uri) as ws:
                        # مراقبة لمدة 3 دقائق قبل دورة المسح القادمة
                        for _ in range(180):
                            try:
                                msg = await asyncio.wait_for(ws.recv(), timeout=5)
                                await self._process_price_update(json.loads(msg))
                            except asyncio.TimeoutError:
                                continue
                            except Exception:
                                break
                            await asyncio.sleep(1)
                else:
                    await asyncio.sleep(15)

            except Exception as e:
                print(f"⚠️ خطأ في المراقبة الرئيسية: {e}")
                await asyncio.sleep(10)

    async def _process_price_update(self, message):
        if 'data' not in message: return
        data = message['data']
        symbol, current_price = data['s'], float(data['c'])

        async with AsyncSessionLocal() as session:
            res = await session.execute(select(PaperTrade).where((PaperTrade.symbol == symbol) & (PaperTrade.status == "OPEN")))
            for trade in res.scalars().all():
                closed, status = False, ""
                
                # التحقق من شروط الإغلاق (BUY/SELL)
                if trade.type == "BUY":
                    if current_price >= trade.take_profit: closed, status = True, "WON"
                    elif current_price <= trade.stop_loss: closed, status = True, "LOST"
                elif trade.type == "SELL":
                    if current_price <= trade.take_profit: closed, status = True, "WON"
                    elif current_price >= trade.stop_loss: closed, status = True, "LOST"

                if closed:
                    # --- توليد التقرير التحليلي الواسع ---
                    reason = self._generate_analysis(trade, status)
                    
                    trade.status = status
                    trade.exit_price = current_price
                    trade.closed_at = datetime.utcnow()
                    trade.result_reason = reason
                    # حساب الربح/الخسارة التقريبي
                    pnl_percent = ((current_price - trade.entry_price) / trade.entry_price) * 100
                    trade.pnl = (trade.amount * pnl_percent / 100) if status == "WON" else -(trade.amount * 0.02) # افتراض وقف 2%
                    
                    await session.commit()

                    # إشعار صفقات النخبة فقط (أو التقارير الشاملة)
                    if self.bot:
                        icon = "✅" if status == "WON" else "❌"
                        elite_tag = "🌟 *صفقة نخبة*" if trade.is_elite else "🔬 *سجل تعلم*"
                        
                        report_msg = (
                            f"{icon} {elite_tag}\n\n"
                            f"🪙 العملة: #{symbol}\n"
                            f"🏁 النتيجة: {status}\n"
                            f"💵 سعر الخروج: `{current_price}`\n\n"
                            f"🧠 *التحليل العميق:*\n{reason}"
                        )
                        
                        # نرسل الإشعار فوراً إذا كانت نخبة، أو إذا كانت مخفية لغرض التدريب
                        await self.bot.send_message(self.chat_id, report_msg, parse_mode='Markdown')

    def _generate_analysis(self, trade, status):
        """توليد تفسير منطقي للنتيجة بناءً على البيانات المخزنة"""
        try:
            snapshot = json.loads(trade.technical_snapshot) if trade.technical_snapshot else {}
            rsi = snapshot.get("RSI", "N/A")
            regime = snapshot.get("Regime", "UNKNOWN")
            
            if status == "WON":
                return f"نجحت الصفقة بتوافق مع نظام {regime}. مؤشر RSI كان عند {rsi} مما وفر عزماً كافياً للوصول للهدف."
            else:
                if regime == "RISK_OFF":
                    return f"فشلت الصفقة بسبب ضغط السوق العام (RISK_OFF). التحليل الفني لم يصمد أمام اتجاه السوق الهابط."
                return f"فشلت الصفقة نتيجة تذبذب عالي (Volatility Trap). رغم أن RSI كان {rsi}، إلا أن السعر كسر الوقف قبل الارتداد."
        except:
            return "تم الإغلاق بناءً على مستويات السعر المحددة."
