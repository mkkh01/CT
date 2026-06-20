import asyncio
import logging
from Core.redis_manager import redis_client
from datetime import datetime
from sqlalchemy import select
from database import AsyncSessionLocal, ShadowTrade, TrackedCoin

logger = logging.getLogger(__name__)

class ShadowMonitor:
    def __init__(self, bot=None):
        self.bot = bot
        self.is_running = False

    async def check_shadow_trades(self):
        """مراقبة صفقات الظل المفتوحة وتحديث نتائجها"""
        self.is_running = True
        logger.info("📉 [SHADOW] بدء مراقبة صفقات الظل (Shadow Trades)...")
        while self.is_running:
            try:
                async with AsyncSessionLocal() as session:
                    # جلب الصفقات المفتوحة
                    res = await session.execute(select(ShadowTrade).where(ShadowTrade.status == "OPEN"))
                    open_trades = res.scalars().all()
                    
                    if not open_trades:
                        logger.debug("ℹ️ [SHADOW] لا توجد صفقات ظل مفتوحة حالياً.")
                        await asyncio.sleep(30)
                        continue

                    logger.info(f"🔍 [SHADOW] فحص {len(open_trades)} صفقة ظل مفتوحة...")
                    
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
                        # Ensure we check symbol case-insensitively against our prices dict
                        current_price = None
                        for sym, data in prices.items():
                            if sym.upper() == trade.symbol.upper():
                                current_price = data.get('price')
                                break
                        
                        if not current_price: 
                            logger.debug(f"⚠️ [SHADOW] لم يتم العثور على سعر لحظي لـ {trade.symbol} في الكاش.")
                            continue
                        
                        current_price = float(current_price)
                        hit_tp = current_price >= trade.take_profit
                        hit_sl = current_price <= trade.stop_loss

                        if hit_tp or hit_sl:
                            trade.status = "WON" if hit_tp else "LOST"
                            trade.exit_price = current_price
                            trade.closed_at = datetime.now()
                            pnl_pct = ((current_price - trade.entry_price) / trade.entry_price) * 100
                            trade.pnl = pnl_pct
                            
                            # كتابة التقرير التحليلي المشروح
                            reasoning = f"تحليل النتيجة لـ {trade.symbol}:\n"
                            if hit_tp:
                                reasoning += f"✅ نجحت الصفقة بضرب الهدف. السبب: توافق الاتجاه مع الجلسة ({trade.trading_session}) وقوة الزخم."
                                logger.info(f"🎯 [SHADOW] {trade.symbol}: ضرب الهدف التجريبي! PnL: {pnl_pct:.2f}%")
                            else:
                                reasoning += f"❌ فشلت الصفقة بضرب الوقف. السبب المحتمل: تذبذب عالي أو انعكاس مفاجئ في جلسة {trade.trading_session}."
                                logger.info(f"📉 [SHADOW] {trade.symbol}: ضرب الوقف التجريبي! PnL: {pnl_pct:.2f}%")
                            
                            trade.reasoning_report += f"\n[RESULT] {reasoning}"
                            logger.info(f"📉 [SHADOW LEARN] تم إغلاق صفقة ظل لـ {trade.symbol} بنتيجة: {trade.status}")
                    
                    await session.commit()
            except asyncio.CancelledError:
                logger.info("🛑 [SHADOW MONITOR] تم إلغاء المهمة. إغلاق آمن...")
                self.is_running = False
                break
            except Exception as e:
                logger.error(f"⚠️ [SHADOW MONITOR] Error: {e}", exc_info=True)
            
            try:
                await asyncio.sleep(10)
            except asyncio.CancelledError:
                self.is_running = False
                break
