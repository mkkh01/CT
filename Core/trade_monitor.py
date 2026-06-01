import asyncio
import json
import websockets
import os
from datetime import datetime
from sqlalchemy import select
from database import AsyncSessionLocal, PaperTrade, TrackedCoin, UserConfig
from config import ADMIN_ID

# ملف لتخزين الأسعار اللحظية لتبادلها بين الوحدات
PRICES_CACHE_FILE = "/tmp/live_prices.json"

try:
    from Core.ai_engine import AIEngine
    AI_ENGINE_AVAILABLE = True
except ImportError:
    AIEngine = None
    AI_ENGINE_AVAILABLE = False

class TradeMonitor:
    def __init__(self, bot=None):
        self.bot = bot
        self.chat_id = ADMIN_ID
        self.is_running = False
        self.live_prices = {}

    def _save_prices(self):
        """حفظ الأسعار في ملف مؤقت ليقرأها البوت والمحرك"""
        try:
            with open(PRICES_CACHE_FILE, 'w') as f:
                json.dump(self.live_prices, f)
        except:
            pass

    async def check_prices(self):
        ai = AIEngine(bot=self.bot, chat_id=self.chat_id) if AI_ENGINE_AVAILABLE and AIEngine else None
        self.is_running = True
        print("📡 [MONITOR] انطلاق نظام المراقبة المركزي V4.0")
        
        while self.is_running:
            try:
                async with AsyncSessionLocal() as session:
                    # 1. جلب جميع العملات المضافة لمراقبتها
                    coins_res = await session.execute(select(TrackedCoin))
                    tracked_coins = coins_res.scalars().all()
                    symbols = [c.symbol for c in tracked_coins]
                    
                    if not symbols:
                        print("😴 [MONITOR] لا توجد عملات مضافة للمراقبة. انتظر 30 ثانية...")
                        await asyncio.sleep(30)
                        continue

                    # 2. بناء اتصال WebSocket لجميع العملات (المضافة + المفتوحة)
                    streams = [f"{s.lower()}@miniTicker" for s in symbols]
                    uri = f"wss://stream.binance.com:9443/stream?streams={'/'.join(streams)}"
                    
                    print(f"🔌 [MONITOR] جاري الاتصال بـ WebSocket لـ {len(symbols)} عملة...")
                    
                    async with websockets.connect(uri, ping_interval=20, ping_timeout=60) as ws:
                        print("✅ [MONITOR] تم الاتصال بنجاح. جاري استقبال الأسعار اللحظية.")
                        
                        # حلقة استقبال البيانات
                        last_analysis_time = datetime.now()
                        
                        while self.is_running:
                            try:
                                msg = await asyncio.wait_for(ws.recv(), timeout=5)
                                data = json.loads(msg)['data']
                                symbol = data['s']
                                current_price = float(data['c'])
                                
                                # تحديث الذاكرة والملف
                                self.live_prices[symbol] = {
                                    'price': current_price,
                                    'open': float(data['o']),
                                    'high': float(data['h']),
                                    'low': float(data['l']),
                                    'time': datetime.now().strftime('%H:%M:%S')
                                }
                                self._save_prices()
                                # إضافة Log للتأكد من وصول السعر
                                if len(self.live_prices) % 5 == 0: # تقليل عدد السجلات لتجنب الزحام
                                    print(f"📊 [MONITOR] تحديث السعر: {symbol} -> {current_price}")

                                # 3. فحص الصفقات المفتوحة لهذه العملة
                                await self._check_open_trades(symbol, current_price)

                                # 4. تشغيل التحليل الدوري (كل 5 دقائق لكل عملة لتقليل الضغط)
                                if (datetime.now() - last_analysis_time).seconds > 300:
                                    if ai:
                                        print(f"🧠 [MONITOR] بدء جولة التحليل الدوري...")
                                        for s in symbols:
                                            await ai.analyze_and_trade(s)
                                            await asyncio.sleep(1)
                                    last_analysis_time = datetime.now()

                            except asyncio.TimeoutError:
                                continue
                            except Exception as e:
                                print(f"⚠️ [MONITOR] خطأ في معالجة البيانات: {e}")
                                break # أعد الاتصال

            except Exception as e:
                print(f"🔌 [MONITOR] فشل الاتصال أو انقطع: {e}. إعادة المحاولة بعد 10 ثوانٍ...")
                await asyncio.sleep(10)

    async def _check_open_trades(self, symbol, current_price):
        """فحص وإغلاق الصفقات المفتوحة بناءً على السعر الجديد"""
        async with AsyncSessionLocal() as session:
            res = await session.execute(
                select(PaperTrade).where(
                    (PaperTrade.symbol == symbol) & 
                    (PaperTrade.status == "OPEN")
                )
            )
            
            for trade in res.scalars().all():
                closed, status = False, ""
                if trade.type == "BUY":
                    if trade.take_profit and current_price >= trade.take_profit:
                        closed, status = True, "WON"
                    elif trade.stop_loss and current_price <= trade.stop_loss:
                        closed, status = True, "LOST"
                elif trade.type == "SELL":
                    if trade.take_profit and current_price <= trade.take_profit:
                        closed, status = True, "WON"
                    elif trade.stop_loss and current_price >= trade.stop_loss:
                        closed, status = True, "LOST"

                if closed:
                    trade.status = status
                    trade.exit_price = current_price
                    trade.closed_at = datetime.utcnow()
                    
                    if trade.type == "BUY":
                        pnl_pct = ((current_price - trade.entry_price) / trade.entry_price) * 100
                    else:
                        pnl_pct = ((trade.entry_price - current_price) / trade.entry_price) * 100
                    
                    trade.pnl = round((trade.amount * pnl_pct) / 100, 4)
                    await session.commit()
                    
                    print(f"💰 [MONITOR] تم إغلاق صفقة {symbol} بنتيجة {status}")
                    
                    if self.bot:
                        icon = "✅" if status == "WON" else "❌"
                        msg = (f"{icon} *تم إغلاق صفقة*\n\n"
                               f"🪙 العملة: #{symbol}\n"
                               f"🏁 النتيجة: {status}\n"
                               f"💵 الدخول: `{trade.entry_price}`\n"
                               f"💵 الخروج: `{current_price}`\n"
                               f"📊 الربح: `{trade.pnl:.2f} USDT`")
                        try:
                            await self.bot.send_message(self.chat_id, msg, parse_mode='Markdown')
                        except:
                            pass
