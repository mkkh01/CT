import pandas as pd
import ccxt.async_support as ccxt
from database import AsyncSessionLocal, LiveTrade, ShadowTrade, UserConfig, TrackedCoin
from sqlalchemy import select
from strategies_v2 import InstitutionalStrategiesV2 as InstitutionalStrategies
from Core.whale_tracker_v2 import WhaleTrackerV2
from Core.news_analyzer import NewsAnalyzer
from Core.risk_manager import RiskManager
from Core.smc_engine import SMCEngine
from Core.volume_engine import VolumeEngine
from Core.market_context import MarketContext
from datetime import datetime, time
import asyncio
import json
import os
from Core.redis_manager import redis_client

class AIEngine:
    def __init__(self, bot=None, chat_id=None):
        self.strategies = InstitutionalStrategies()
        self.bot = bot
        self.chat_id = chat_id
        self.exchange = ccxt.binance({'enableRateLimit': True, 'options': {'defaultType': 'spot'}})
        self.whale_tracker = WhaleTrackerV2(bot=bot, chat_id=chat_id)
        self.news_analyzer = NewsAnalyzer(bot=bot, chat_id=chat_id)
        self.risk_manager = RiskManager()
        self.smc_engine = SMCEngine()
        self.volume_engine = VolumeEngine()
        self.market_context = MarketContext()

    def get_trading_session(self):
        """تحديد جلسة التداول الحالية بناءً على توقيت UTC"""
        now = datetime.utcnow().time()
        if time(8, 0) <= now <= time(16, 0): return "London"
        if time(13, 0) <= now <= time(21, 0): return "New York"
        if time(0, 0) <= now <= time(8, 0): return "Tokyo/Sydney"
        return "Asian/Late NY"

    async def calculate_probability(self, symbol, score, session):
        """محرك الاحتمالات (Probability Engine) - تجريبي بناءً على المعطيات"""
        # في المستقبل سيتم ربط هذا بقاعدة بيانات صفقات الظل التاريخية
        base_prob = score * 0.8
        if session in ["London", "New York"]: base_prob += 10
        return min(95, base_prob)

    async def get_higher_timeframe_data(self, symbol, current_tf):
        tf_map = {"5m": "15m", "15m": "1h", "30m": "4h", "1h": "4h", "4h": "1d"}
        higher_tf = tf_map.get(current_tf, "1d")
        redis_key = f"htf_cache_{symbol}_{higher_tf}"
        try:
            cached_data = redis_client.get_data(redis_key)
            if cached_data:
                return pd.DataFrame(cached_data, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            
            await asyncio.sleep(1)
            ohlcv = await self.exchange.fetch_ohlcv(symbol, higher_tf, limit=100)
            redis_client.set_data(redis_key, ohlcv, ex=1800) # كاش لمدة 30 دقيقة
            return pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        except Exception as e:
            return None

    async def analyze_and_trade(self, symbol: str, **kwargs):
        print(f"🔍 [SCANNER] جاري فحص العملة: {symbol}...")
        async with AsyncSessionLocal() as session:
            cfg_res = await session.execute(select(UserConfig).where(UserConfig.telegram_id == self.chat_id))
            cfg = cfg_res.scalars().first()
            if not cfg or not cfg.is_active or cfg.emergency_stop: return
            
            coin_res = await session.execute(select(TrackedCoin).where(TrackedCoin.symbol == symbol))
            coin = coin_res.scalars().first()
            if not coin or not coin.enabled: 
                print(f"⚠️ [SCANNER] العملة {symbol} غير مفعلة في الإعدادات.")
                return

            try:
                hist_key = f"hist_cache_{symbol}_{coin.timeframe}"
                ohlcv = redis_client.get_data(hist_key)
                
                if not ohlcv:
                    # تقليل وتيرة جلب البيانات التاريخية لتجنب الحظر
                    await asyncio.sleep(5)
                    try:
                        ohlcv = await self.exchange.fetch_ohlcv(symbol, coin.timeframe, limit=100)
                        redis_client.set_data(hist_key, ohlcv, ex=3600)
                    except Exception as e:
                        if "418" in str(e) or "1003" in str(e):
                            print(f"🚫 [BINANCE] IP Banned or Rate Limited. Skipping {symbol}...")
                            return
                        raise e
                
                df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
                
                klines_data = redis_client.get_data("live_klines")
                if klines_data and symbol in klines_data:
                    k = klines_data[symbol]
                    if k.get('x', False):
                        new_row = [datetime.now().timestamp()*1000, k['o'], k['h'], k['l'], k['c'], k['v']]
                        ohlcv.append(new_row)
                        if len(ohlcv) > 300: ohlcv.pop(0)
                        redis_client.set_data(hist_key, ohlcv, ex=3600)
                    df.iloc[-1] = [df.iloc[-1]['timestamp'], k['o'], k['h'], k['l'], k['c'], k['v']]
            except Exception as e:
                print(f"⚠️ [SCANNER ERROR] Error fetching OHLCV for {symbol}: {e}")
                return
            
            # 1. تحليل الأخبار (تم تعطيله لضمان الدقة والاعتماد على السعر والسيولة فقط)
            # is_news_safe = await self.news_analyzer.get_safety_check(symbol)
            # if not is_news_safe:
            #     return

            # 2. تحليل هيكلة السوق و SMC
            print(f"📊 [ANALYSIS] جاري تحليل الاستراتيجيات الفنية لـ {symbol}...")
            df_higher = await self.get_higher_timeframe_data(symbol, coin.timeframe)
            analysis = self.strategies.calculate_combined_score(df, df_higher)
            print(f"📈 [SCORE] {symbol} | Total Score: {analysis['total_score']} | Quality: {analysis['quality_score']}")
            
            # 3. Decision Engine: SMC, Volume, Context (Advanced)
            smc_data = self.smc_engine.detect_structure(df)
            fvgs = self.smc_engine.detect_fvgs(df)
            obs = self.smc_engine.detect_order_blocks(df)
            pd_zones = self.smc_engine.get_premium_discount(df)
            vol_flow = self.volume_engine.get_order_flow_bias(df)
            global_context = await self.market_context.get_global_market_data()
            trend_strength = self.market_context.get_trend_strength(df)
            
            # نظام تقييم ديناميكي (Dynamic Weighting System)
            smc_score = 0
            reasons = []
            
            if smc_data['state'] in ["BOS_UP", "CHoCH_UP", "STRONG_BULLISH"]: 
                smc_score += 35
                reasons.append(f"Structure: {smc_data['state']}")
                
            if any(not f['mitigated'] and f['type'] == 'BULLISH_FVG' for f in fvgs[-5:]):
                smc_score += 15
                reasons.append("Unmitigated Bullish FVG")
                
            if any(not o['mitigated'] and o['type'] == 'BULLISH_OB' for o in obs[-3:]):
                smc_score += 25
                reasons.append("Active Bullish Order Block")
                
            if pd_zones['zone'] == "DISCOUNT":
                smc_score += 10
                reasons.append("Price in Discount Zone")
                
            if vol_flow['bias'] == "AGGRESSIVE_BUYING":
                smc_score += 15
                reasons.append("Aggressive Buying Volume")
                
            if global_context['btc_bias'] == "BULLISH":
                smc_score += 10
                reasons.append("BTC Market Alignment")

            # إزالة الإشارات المتعارضة (Conflict Removal)
            if smc_data['state'] == "BOS_DOWN" or pd_zones['zone'] == "PREMIUM":
                smc_score -= 40
                reasons.append("Conflict: Bearish Structure or Premium Price")

            analysis["total_score"] = smc_score
            analysis["report"] = " | ".join(reasons)
            analysis["quality_score"] = min(100, smc_score)
            
            total_score = analysis["total_score"]
            params = self.strategies.get_trade_params(df)
            current_session = self.get_trading_session()
            
            # Dynamic Weights based on Session & Trend
            weight = 1.0
            if current_session in ["London", "New York"]: weight += 0.2
            if trend_strength == "STRONG": weight += 0.1
            
            total_score *= weight
            prob = await self.calculate_probability(symbol, total_score, current_session)

            # تسجيل صفقة ظل (Shadow Trade) للتعلم
            new_shadow = ShadowTrade(
                symbol=symbol,
                indicators_snapshot=analysis,
                market_state=analysis["market_state"],
                score=total_score,
                entry_price=params["entry"],
                stop_loss=params["sl"],
                take_profit=params["tp"],
                trading_session=current_session,
                probability_score=prob,
                reasoning_report=f"تحليل آلي: {analysis['report']} | الجلسة: {current_session}"
            )
            session.add(new_shadow)
            await session.commit()

            # الفلترة لنظام الـ Live
            # تم تعديل الشروط لتكون أكثر مرونة مع نظام الجودة الجديد
            if total_score < 70 or analysis["quality_score"] < 60:
                print(f"⏭️ [SCANNER] تم تخطي {symbol} (النقاط غير كافية للدخول الحقيقي).")
                return

            # 4. حماية الارتباط (Correlation Guard)
            print(f"🛡️ [RISK] جاري فحص مخاطر الارتباط لـ {symbol}...")
            open_trades_res = await session.execute(select(LiveTrade).where(LiveTrade.status == "OPEN"))
            open_trades = open_trades_res.scalars().all()
            if not self.risk_manager.check_correlation_risk(open_trades, symbol):
                print(f"🚫 [RISK] تم رفض {symbol} بسبب وجود ارتباط عالٍ مع صفقات مفتوحة.")
                return

            # منطق تنفيذ Live Trade
            risk_amount = coin.capital * (coin.risk_percentage / 100)
            sl_dist = abs(params["entry"] - params["sl"])
            if sl_dist <= 0:
                print(f"⚠️ [RISK] تم رفض {symbol} بسبب عدم وجود مسافة وقف خسارة صالحة.")
                return
            amount = risk_amount / (sl_dist / params["entry"])
            if amount <= 0: 
                print(f"⚠️ [RISK] تم رفض {symbol} لأن حجم الصفقة المحسوب صفر.")
                return
            
            # منع تكرار نفس العملة
            if any(t.symbol == symbol for t in open_trades): return

            print(f"🚀 [EXECUTION] تم العثور على فرصة ذهبية! جاري فتح صفقة {symbol}...")
            new_live = LiveTrade(
                symbol=symbol, type="BUY", entry_price=params["entry"], stop_loss=params["sl"],
                take_profit=params["tp"], amount=amount, score=total_score,
                entry_reason=analysis["report"], market_state=analysis["market_state"]
            )
            session.add(new_live)
            await session.commit()
            print(f"✅ [SUCCESS] تم تسجيل صفقة {symbol} بنجاح في النظام.")
