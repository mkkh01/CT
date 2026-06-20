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
        start_process = datetime.now()
        logger.info(f"🔍 [SCANNER] >>> بدء فحص فرصة تداول لـ {symbol.upper()} <<<")
        
        async with AsyncSessionLocal() as session:
            cfg_res = await session.execute(select(UserConfig).where(UserConfig.telegram_id == self.chat_id))
            cfg = cfg_res.scalars().first()
            
            if not cfg or not cfg.is_active or cfg.emergency_stop:
                status = "OFF" if not cfg else ("EMERGENCY" if cfg.emergency_stop else "INACTIVE")
                logger.info(f"⏸️ [SCANNER] تم تخطي {symbol} لأن نظام المستخدم في حالة: {status}")
                return
            
            symbol_db = symbol.upper()
            symbol_cache = symbol.lower()
            
            coin_res = await session.execute(select(TrackedCoin).where(TrackedCoin.symbol == symbol_db))
            coin = coin_res.scalars().first()
            if not coin or not coin.enabled:
                logger.info(f"🚫 [SCANNER] {symbol_db} غير مدرجة أو معطلة في قائمة المراقبة.")
                return

            try:
                hist_key = f"hist_cache_{symbol_cache}_{coin.timeframe}"
                ohlcv = redis_client.get_data(hist_key)
                
                if not ohlcv or not live_data:
                    logger.warning(f"⚠️ [SCANNER] بيانات مفقودة لـ {symbol_db} (Cache: {'Yes' if ohlcv else 'No'}, Live: {'Yes' if live_data else 'No'})")
                    return

                if len(ohlcv) < state_manager.data_threshold:
                    logger.info(f"⏳ [SCANNER] بيانات غير كافية لـ {symbol_db}: {len(ohlcv)}/{state_manager.data_threshold}")
                    return
                
                logger.info(f"📊 [DATA] تم جلب {len(ohlcv)} شمعة لـ {symbol_db} فريم {coin.timeframe}. السعر الحالي: {live_data['c']}")
                
                df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
                df = df.astype({'timestamp': 'float64', 'open': 'float64', 'high': 'float64', 'low': 'float64', 'close': 'float64', 'volume': 'float64'})
                
                new_row = [float(datetime.now().timestamp()*1000), float(live_data['o']), float(live_data['h']), float(live_data['l']), float(live_data['c']), float(live_data['v'])]
                df.iloc[-1] = new_row
                
            except Exception as e:
                logger.error(f"⚠️ [SCANNER ERROR] خطأ في معالجة البيانات لـ {symbol}: {e}")
                return
            
            # 1. تحليل الاستراتيجيات الفنية
            logger.info(f"🛠️ [STRATEGY] جاري استخراج مستويات الدخول والأهداف لـ {symbol_db}...")
            params = self.strategies.get_trade_params(df)
            
            # 2. Decision Engine
            logger.info(f"🧠 [DECISION] بدء تحليل الهيكل المؤسسي (SMC) لـ {symbol_db}...")
            smc_data = self.smc_engine.detect_structure(df)
            pd_zones = self.smc_engine.get_premium_discount(df)
            liq_data = self.smc_engine.detect_liquidity(df)
            vol_data = self.volume_engine.get_volume_bias(df)
            global_context = await self.market_context.get_market_correlations()
            
            total_score = 0
            decision_report = []
            
            # تفصيل نقاط القوة والضعف في السجلات
            # السيولة
            if liq_data['liquidity_sweep']:
                total_score += 25
                decision_report.append("Liquidity Sweep")
                logger.info(f"✅ [SMC] {symbol_db}: تم اكتشاف سحب سيولة مؤسسي (Liquidity Sweep). [+25]")
            else:
                total_score -= 20
                decision_report.append("No Sweep")
                logger.info(f"❌ [SMC] {symbol_db}: لا يوجد سحب سيولة واضح حالياً. [-20]")

            # هيكل السوق
            if smc_data['state'] in ["BOS_UP", "CHoCH_UP"]:
                total_score += 30
                decision_report.append(f"Structure: {smc_data['state']}")
                logger.info(f"✅ [SMC] {symbol_db}: هيكل صاعد مؤكد ({smc_data['state']}). [+30]")
            
            # مناطق السعر
            if pd_zones['zone'] == "DISCOUNT":
                total_score += 15
                decision_report.append("Discount Zone")
                logger.info(f"✅ [SMC] {symbol_db}: السعر في منطقة خصم (Discount Zone) مثالية للشراء. [+15]")
            else:
                total_score -= 15
                decision_report.append("Premium Zone")
                logger.info(f"⚠️ [SMC] {symbol_db}: السعر في منطقة غالية (Premium Zone). [-15]")

            # الفوليوم
            if vol_data['bias'] == "AGGRESSIVE_BUYING":
                total_score += 20
                decision_report.append("Aggressive Buying")
                logger.info(f"✅ [VOLUME] {symbol_db}: ضغط شراء مؤسسي عدواني مكتشف. [+20]")
            
            # سياق السوق (BTC)
            if global_context['btc_bias'] == "BULLISH":
                total_score += 10
                logger.info(f"✅ [MARKET] BTC Bias صاعد، يدعم الحركة. [+10]")
            elif global_context['btc_bias'] == "BEARISH":
                total_score -= 30
                decision_report.append("BTC Bearish")
                logger.info(f"🚨 [MARKET] BTC Bias هابط، مخاطرة عالية جداً! [-30]")

            total_score = max(0, total_score)
            current_session = self.get_trading_session()
            prob = await self.calculate_probability(symbol_db, total_score, current_session)
            
            logger.info(f"📊 [SUMMARY] {symbol_db} | Score: {total_score}/100 | Prob: {prob}% | Session: {current_session}")

            # تسجيل صفقة الظل للتعلم
            new_shadow = ShadowTrade(
                symbol=symbol_db, score=total_score, entry_price=params["entry"],
                stop_loss=params["sl"], take_profit=params["tp"],
                trading_session=current_session, probability_score=prob,
                reasoning_report=" | ".join(decision_report)
            )
            session.add(new_shadow)
            await session.commit()

            # قرار التنفيذ
            if total_score < 70:
                logger.info(f"⏭️ [SCANNER] تم رفض {symbol_db} (النتيجة {total_score} أقل من الحد الأدنى 70).")
                return

            # التحقق من المخاطر قبل التنفيذ النهائي
            open_trades_res = await session.execute(select(LiveTrade).where(LiveTrade.status == "OPEN"))
            open_trades = open_trades_res.scalars().all()
            
            if any(t.symbol == symbol_db for t in open_trades):
                logger.info(f"⏭️ [RISK] {symbol_db}: توجد صفقة مفتوحة بالفعل، لن يتم التكرار.")
                return
                
            if not self.risk_manager.check_correlation_risk(open_trades, symbol_db):
                logger.info(f"⚠️ [RISK] {symbol_db}: تعارض ارتباط (Correlation) مع صفقات مفتوحة.")
                return

            # حساب الحجم والتنفيذ
            risk_amount = coin.capital * (coin.risk_percentage / 100)
            sl_dist = abs(params["entry"] - params["sl"])
            if sl_dist <= 0: return
                
            amount = risk_amount / (sl_dist / params["entry"])
            
            new_live = LiveTrade(
                symbol=symbol_db, type="BUY", entry_price=params["entry"], stop_loss=params["sl"],
                take_profit=params["tp"], amount=amount, score=total_score,
                entry_reason=" | ".join(decision_report)
            )
            session.add(new_live)
            await session.commit()
            
            end_process = datetime.now()
            duration = (end_process - start_process).total_seconds()
            logger.info(f"🚀 [EXECUTION] تم فتح صفقة حقيقية لـ {symbol_db} بنجاح! السعر: {params['entry']} | الوقت المستغرق: {duration:.2f} ثانية.")
