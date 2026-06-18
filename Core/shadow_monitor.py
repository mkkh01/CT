import asyncio
import json
import os
from Core.redis_manager import redis_client
from datetime import datetime
from sqlalchemy import select
from database import AsyncSessionLocal, ShadowTrade, TrackedCoin

class ShadowMonitor:
    def __init__(self, bot=None):
        self.bot = bot

    async def check_shadow_trades(self):
        """مراقبة صفقات الظل المفتوحة وتحديث نتائجها"""
        self.is_running = True
        while self.is_running:
            try:
                async with AsyncSessionLocal() as session:
                    # جلب الصفقات المفتوحة
                    res = await session.execute(select(ShadowTrade).where(ShadowTrade.status == "OPEN"))
                    open_trades = res.scalars().all()
                    
                    if not open_trades:
                        await asyncio.sleep(30)
                        continue

                    # جلب الأسعار اللحظية من الكاش
                    # جلب الأسعار اللحظية من الكاش لكل رمز على حدة
                    prices = {}
                    async with AsyncSessionLocal() as s_session:
                        coins_res = await s_session.execute(select(TrackedCoin).where(TrackedCoin.enabled == True))
                        tracked_symbols = [c.symbol.strip() for c in coins_res.scalars().all() if c.symbol and c.symbol.strip()]

                    for symbol in tracked_symbols:
                        price_data = redis_client.get_data(f"live_prices_{symbol}")
                        if price_data:
                            prices[symbol] = price_data

                    for trade in open_trades:
                        current_price = prices.get(trade.symbol, {}).get('price')
                        if not current_price: continue
                        
                        current_price = float(current_price)
                        hit_tp = current_price >= trade.take_profit
                        hit_sl = current_price <= trade.stop_loss

                        if hit_tp or hit_sl:
                            trade.status = "WON" if hit_tp else "LOST"
                            trade.exit_price = current_price
                            trade.closed_at = datetime.now()
                            trade.pnl = ((current_price - trade.entry_price) / trade.entry_price) * 100
                            
                            # كتابة التقرير التحليلي المشروح
                            reasoning = f"تحليل النتيجة لـ {trade.symbol}:\n"
                            if hit_tp:
                                reasoning += f"✅ نجحت الصفقة بضرب الهدف. السبب: توافق الاتجاه مع الجلسة ({trade.trading_session}) وقوة الزخم."
                            else:
                                reasoning += f"❌ فشلت الصفقة بضرب الوقف. السبب المحتمل: تذبذب عالي أو انعكاس مفاجئ في جلسة {trade.trading_session}."
                            
                            trade.reasoning_report += f"\n[RESULT] {reasoning}"
                            print(f"📉 [SHADOW LEARN] تم إغلاق صفقة ظل لـ {trade.symbol} بنتيجة: {trade.status}")
                    
                    await session.commit()
            except asyncio.CancelledError:
                print("🛑 [SHADOW MONITOR] Task was cancelled. Shutting down gracefully.")
                self.is_running = False
                break
            except Exception as e:
                print(f"⚠️ [SHADOW MONITOR] Error: {e}")
            
            try:
                await asyncio.sleep(10)
            except asyncio.CancelledError:
                print("🛑 [SHADOW MONITOR] Task was cancelled during sleep. Shutting down gracefully.")
                self.is_running = False
                break
