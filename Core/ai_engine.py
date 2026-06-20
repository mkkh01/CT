import pandas as pd
from database import AsyncSessionLocal, LiveTrade, ShadowTrade, UserConfig, TrackedCoin
from sqlalchemy import select
from strategies_v2 import InstitutionalStrategiesV2 as InstitutionalStrategies
from Core.whale_tracker_v2 import WhaleTrackerV2
from Core.news_analyzer import NewsAnalyzer
from Core.risk_manager import RiskManager
from Core.smc_engine import SMCEngine
from Core.volume_engine import VolumeEngine
from Core.market_context import MarketContext
from Core.api_guard import api_guard
from datetime import datetime, time
import asyncio
import json
import os
import logging
from Core.redis_manager import redis_client
from Core.state_manager import state_manager

logger = logging.getLogger(__name__)

class AIEngine:
    def __init__(self, bot=None, chat_id=None):
        self.strategies = InstitutionalStrategies()
        self.bot = bot
        self.chat_id = chat_id

        self.whale_tracker = WhaleTrackerV2(bot=bot, chat_id=chat_id)
        self.news_analyzer = NewsAnalyzer(bot=bot, chat_id=chat_id)
        self.risk_manager = RiskManager()
        self.smc_engine = SMCEngine()
        self.volume_engine = VolumeEngine()
        self.market_context = MarketContext()

    def get_trading_session(self):
        now = datetime.utcnow().time()
        if time(8, 0) <= now <= time(16, 0): return "London"
        if time(13, 0) <= now <= time(21, 0): return "New York"
        if time(0, 0) <= now <= time(8, 0): return "Tokyo/Sydney"
        return "Asian/Late NY"

    async def calculate_probability(self, symbol, score, session):
        base_prob = score * 0.8
        if session in ["London", "New York"]: base_prob += 10
        return min(95, base_prob)

    async def get_higher_timeframe_data(self, symbol, current_tf):
        return None

    async def analyze_and_trade(self, symbol: str, live_data=None, **kwargs):
        logger.info(f"🔍 [AI ENGINE] بدء عملية التحليل لـ {symbol}...")
        async with AsyncSessionLocal() as session:
            cfg_res = await session.execute(select(UserConfig).where(UserConfig.telegram_id == self.chat_id))
            cfg = cfg_res.scalars().first()
            if not cfg:
                logger.warning(f"⚠️ [AI ENGINE] لم يتم العثور على إعدادات للمستخدم {self.chat_id}")
                return
            if not cfg.is_active or cfg.emergency_stop:
                logger.info(f"⏸️ [AI ENGINE] النظام متوقف حالياً للمستخدم {self.chat_id} (Active: {cfg.is_active}, Emergency: {cfg.emergency_stop})")
                return
            
            # Ensure symbol is uppercase for database lookup
            symbol_db = symbol.upper()
            # Ensure symbol is lowercase for cache lookup
            symbol_cache = symbol.lower()
            
            coin_res = await session.execute(select(TrackedCoin).where(TrackedCoin.symbol == symbol_db))
            coin = coin_res.scalars().first()
            if not coin:
                logger.warning(f"⚠️ [AI ENGINE] العملة {symbol_db} غير موجودة في قائمة المراقبة.")
                return
            if not coin.enabled:
                logger.info(f"🚫 [AI ENGINE] العملة {symbol_db} معطلة حالياً.")
                return

            try:
                hist_key = f"hist_cache_{symbol_cache}_{coin.timeframe}"
                ohlcv = redis_client.get_data(hist_key)
                
                if not ohlcv:
                    logger.warning(f"⚠️ [AI ENGINE] لا توجد بيانات تاريخية في الكاش لـ {symbol_db} ({coin.timeframe})")
                    return
                
                if not live_data:
                    logger.warning(f"⚠️ [AI ENGINE] لا توجد بيانات حية لـ {symbol_db}")
                    return

                if len(ohlcv) < state_manager.data_threshold:
                    logger.info(f"⏳ [AI ENGINE] بيانات غير كافية لـ {symbol_db}: {len(ohlcv)}/{state_manager.data_threshold}")
                    return
                
                logger.info(f"📊 [AI ENGINE] معالجة البيانات لـ {symbol_db}: {len(ohlcv)} شمعة تاريخية متاحة.")
                # إنشاء DataFrame مع تحديد أنواع البيانات لتجنب التحذيرات
                df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
                df = df.astype({'timestamp': 'float64', 'open': 'float64', 'high': 'float64', 'low': 'float64', 'close': 'float64', 'volume': 'float64'})
                
                if live_data:
                    new_row = [float(datetime.now().timestamp()*1000), float(live_data['o']), float(live_data['h']), float(live_data['l']), float(live_data['c']), float(live_data['v'])]
                    df.iloc[-1] = new_row
            except Exception as e:
                logger.error(f"⚠️ [SCANNER ERROR] Error processing OHLCV for {symbol}: {e}", exc_info=True)
                return
            
            # 1. تحليل الاستراتيجيات الفنية
            logger.info(f"🛠️ [AI ENGINE] استخراج المعايير الفنية لـ {symbol_db}...")
            df_higher = await self.get_higher_timeframe_data(symbol, coin.timeframe)
            params = self.strategies.get_trade_params(df)
            
            # 2. Decision Engine
            logger.info(f"🧠 [AI ENGINE] تشغيل محرك القرار (Decision Engine) لـ {symbol_db}...")
            smc_data = self.smc_engine.detect_structure(df)
            pd_zones = self.smc_engine.get_premium_discount(df)
            liq_data = self.smc_engine.detect_liquidity(df)
            vol_data = self.volume_engine.get_volume_bias(df)
            global_context = await self.market_context.get_market_correlations()
            higher_regime = self.market_context.detect_market_regime(df_higher) if df_higher is not None else "UNKNOWN"
            
            total_score = 0
            decision_report = []
            
            # تقييم السيولة
            if not liq_data['liquidity_sweep']:
                total_score -= 20
                decision_report.append("Waiting for Liquidity Sweep")
                logger.info(f"💧 [SMC] {symbol_db}: لا يوجد سحب سيولة (Liquidity Sweep) - تم خصم 20 نقطة.")
            else:
                total_score += 25
                decision_report.append("Liquidity Sweep Detected")
                logger.info(f"💧 [SMC] {symbol_db}: تم اكتشاف سحب سيولة! +25 نقطة.")

            # تقييم هيكل السوق
            if smc_data['state'] in ["BOS_UP", "CHoCH_UP"]:
                total_score += 30
                decision_report.append(f"Structure Shift: {smc_data['state']}")
                logger.info(f"📈 [SMC] {symbol_db}: تغيير في الهيكل ({smc_data['state']}) +30 نقطة.")
            
            # تقييم مناطق العرض والطلب
            if pd_zones['zone'] == "DISCOUNT":
                total_score += 15
                decision_report.append("Discount Zone")
                logger.info(f"🎯 [SMC] {symbol_db}: السعر في منطقة خصم (Discount) +15 نقطة.")
            else:
                total_score -= 15
                decision_report.append("Premium Zone")
                logger.info(f"⚠️ [SMC] {symbol_db}: السعر في منطقة غالية (Premium) - تم خصم 15 نقطة.")

            # تقييم الفوليوم المؤسسي
            if vol_data['bias'] == "AGGRESSIVE_BUYING":
                total_score += 20
                decision_report.append("Institutional Buying Pressure")
                logger.info(f"📊 [VOLUME] {symbol_db}: ضغط شراء مؤسسي قوي +20 نقطة.")
            
            # تقييم سياق السوق العام (بيتكوين)
            if global_context['btc_bias'] == "BULLISH":
                total_score += 10
                logger.info(f"🧡 [MARKET] BTC Bias: Bullish +10 نقاط.")
            elif global_context['btc_bias'] == "BEARISH":
                total_score -= 30
                decision_report.append("Global Market Bias: Bearish")
                logger.info(f"🧡 [MARKET] BTC Bias: Bearish - تم خصم 30 نقطة.")

            # التحقق من تعارض الفريمات
            if higher_regime == "TRENDING_DOWN" and smc_data['state'] == "CHoCH_UP":
                total_score -= 25
                decision_report.append("Conflict: Counter-Trend")
                logger.info(f"⚠️ [CONTEXT] {symbol_db}: تعارض مع الاتجاه العام للفريم الأكبر - تم خصم 25 نقطة.")

            total_score = max(0, total_score)
            current_session = self.get_trading_session()
            prob = await self.calculate_probability(symbol_db, total_score, current_session)
            
            logger.info(f"🏁 [AI ENGINE] النتيجة النهائية لـ {symbol_db}: {total_score}/100 | الاحتمالية: {prob}% | الجلسة: {current_session}")

            new_shadow = ShadowTrade(
                symbol=symbol_db, score=total_score, entry_price=params["entry"],
                stop_loss=params["sl"], take_profit=params["tp"],
                trading_session=current_session, probability_score=prob,
                reasoning_report=" | ".join(decision_report)
            )
            session.add(new_shadow)
            await session.commit()
            logger.info(f"📝 [SHADOW] تم تسجيل صفقة ظل لـ {symbol_db} للتعلم الآلي.")

            if total_score < 70:
                logger.info(f"ℹ️ [ANALYSIS] {symbol_db} rejected. Score: {total_score}/100. Reasons: {', '.join(decision_report)}")
                return

            # التحقق من الصفقات المفتوحة والمخاطر
            open_trades_res = await session.execute(select(LiveTrade).where(LiveTrade.status == "OPEN"))
            open_trades = open_trades_res.scalars().all()
            
            if any(t.symbol == symbol_db for t in open_trades):
                logger.info(f"⏭️ [LIVE] {symbol_db}: توجد صفقة مفتوحة بالفعل، تخطي...")
                return
                
            if not self.risk_manager.check_correlation_risk(open_trades, symbol_db):
                logger.info(f"⚠️ [RISK] {symbol_db}: مخاطرة ارتباط عالية مع الصفقات المفتوحة، تم الإلغاء.")
                return

            # حساب حجم الصفقة
            risk_amount = coin.capital * (coin.risk_percentage / 100)
            sl_dist = abs(params["entry"] - params["sl"])
            if sl_dist <= 0:
                logger.error(f"❌ [RISK] {symbol_db}: مسافة وقف الخسارة غير صالحة (0).")
                return
                
            amount = risk_amount / (sl_dist / params["entry"])
            logger.info(f"💰 [LIVE] {symbol_db}: تنفيذ صفقة حقيقية! السعر: {params['entry']}, الوقف: {params['sl']}, الهدف: {params['tp']}, الحجم: {amount:.2f} USDT")
            
            new_live = LiveTrade(
                symbol=symbol_db, type="BUY", entry_price=params["entry"], stop_loss=params["sl"],
                take_profit=params["tp"], amount=amount, score=total_score,
                entry_reason=" | ".join(decision_report)
            )
            session.add(new_live)
            await session.commit()
            logger.info(f"🚀 [LIVE] تم إدراج صفقة {symbol_db} في قاعدة البيانات بنجاح.")
