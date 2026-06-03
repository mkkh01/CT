import asyncio
import json
import websockets
import os
from datetime import datetime
from sqlalchemy import select
from database import AsyncSessionLocal, PaperTrade, TrackedCoin, UserConfig
from config import ADMIN_ID

# ملفات الذاكرة اللحظية لتبادل البيانات مع البوت والمحرك
PRICES_CACHE_FILE = "/tmp/live_prices.json"
KLINES_CACHE_FILE = "/tmp/live_klines.json"

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
        self.live_klines = {} # تخزين آخر الشموع للتحليل

    def _save_data(self):
        """حفظ الأسعار والشموع في ملفات مؤقتة"""
        try:
            with open(PRICES_CACHE_FILE, 'w') as f:
                json.dump(self.live_prices, f)
            with open(KLINES_CACHE_FILE, 'w') as f:
                json.dump(self.live_klines, f)
        except:
            pass

    async def check_prices(self):
        ai = AIEngine(bot=self.bot, chat_id=self.chat_id) if AI_ENGINE_AVAILABLE and AIEngine else None
        self.is_running = True
        print("📡 [MONITOR] انطلاق نظام WebSocket المركزي V5.0 (بدون HTTP)")
        
        while self.is_running:
            try:
                async with AsyncSessionLocal() as session:
                    coins_res = await session.execute(select(TrackedCoin))
                    tracked_coins = coins_res.scalars().all()
                    symbols = [c.symbol for c in tracked_coins]
                    
                    if not symbols:
                        print("😴 [MONITOR] لا توجد عملات مضافة. انتظر 30 ثانية...")
                        await asyncio.sleep(30)
                        continue

                    # الاشتراك في بث الأسعار (@miniTicker) وبث الشموع (@kline_15m)
                    streams = []
                    for s in symbols:
                        s_lower = s.lower()
                        streams.append(f"{s_lower}@miniTicker")
                        streams.append(f"{s_lower}@kline_15m") # يمكنك تغيير الفريم هنا
                    
                    uri = f"wss://stream.binance.com:9443/stream?streams={'/'.join(streams)}"
                    print(f"🔌 [MONITOR] جاري الاتصال بالبث المباشر لـ {len(symbols)} عملة...")
                    
                    async with websockets.connect(uri, ping_interval=20, ping_timeout=60) as ws:
                        print("✅ [MONITOR] متصل بالبث المباشر. صفر طلبات HTTP الآن.")
                        
                        last_analysis_time = datetime.now()
                        
                        while self.is_running:
                            try:
                                msg = await asyncio.wait_for(ws.recv(), timeout=5)
                                payload = json.loads(msg)
                                stream = payload['stream']
                                data = payload['data']
                                symbol = data['s']
                                
                                if 'miniTicker' in stream:
                                    current_price = float(data['c'])
                                    self.live_prices[symbol] = {
                                        'price': current_price,
                                        'open': float(data['o']),
                                        'change': ((current_price - float(data['o'])) / float(data['o'])) * 100,
                                        'time': datetime.now().strftime('%H:%M:%S')
                                    }
                                    # فحص الصفقات فوراً عند تغير السعر
                                    await self._check_open_trades(symbol, current_price)
                                
                                elif 'kline' in stream:
                                    k = data['k']
                                    # تخزين بيانات الشمعة للتحليل
                                    self.live_klines[symbol] = {
                                        'o': float(k['o']), 'h': float(k['h']), 
                                        'l': float(k['l']), 'c': float(k['c']), 
                                        'v': float(k['v']), 'closed': k['x']
                                    }
                                
                                self._save_data()

                                # تشغيل التحليل الدوري (كل 60 ثانية) باستخدام البيانات المخزنة
                                if (datetime.now() - last_analysis_time).seconds >= 60:
                                    if ai:
                                        print(f"🧠 [MONITOR] بدء التحليل الذكي من بيانات WebSocket...")
                                        for s in symbols:
                                            # نمرر السعر الحالي من الذاكرة للمحرك
                                            price = self.live_prices.get(s, {}).get('price')
                                            if price:
                                                await ai.analyze_and_trade(s, current_price=price)
                                            await asyncio.sleep(0.1) # تأخير بسيط جداً
                                    last_analysis_time = datetime.now()

                            except asyncio.TimeoutError:
                                continue
                            except Exception as e:
                                print(f"⚠️ [MONITOR] خطأ في البث: {e}")
                                break

            except Exception as e:
                print(f"🔌 [MONITOR] انقطع الاتصال: {e}. إعادة المحاولة بعد 10 ثوانٍ...")
                await asyncio.sleep(10)

    async def _check_open_trades(self, symbol, current_price):
        """فحص وإغلاق الصفقات المفتوحة"""
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
                
                if closed:
                    trade.status = status
                    trade.exit_price = current_price
                    trade.closed_at = datetime.utcnow()
                    pnl_pct = ((current_price - trade.entry_price) / trade.entry_price) * 100
                    trade.pnl = round((trade.amount * pnl_pct) / 100, 4)
                    await session.commit()
                    print(f"💰 [MONITOR] تم إغلاق صفقة {symbol} بنتيجة {status}")
                    
                    if self.bot:
                        icon = "✅" if status == "WON" else "❌"
                        msg = (f"{icon} *تم إغلاق صفقة*\n\n"
                               f"🪙 العملة: #{symbol}\n"
                               f"🏁 النتيجة: {status}\n"
                               f"📊 الربح: `{trade.pnl:.2f} USDT`")
                        try:
                            await self.bot.send_message(self.chat_id, msg, parse_mode='Markdown')
                        except: pass
