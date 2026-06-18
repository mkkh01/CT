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
from Core.api_guard import api_guard
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
        """محرك الاحتمالات (Probability Engine)"""
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
            
            await api_guard.check_wait(1)
            ohlcv = await self.exchange.fetch_ohlcv(symbol, higher_tf, limit=100)
            api_guard.update_weight(self.exchange.last_response_headers.get('X-MBX-USED-WEIGHT-1M', 0))
            redis_client.set_data(redis_key, ohlcv, ex=1800)
            return pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        except Exception as e:
            if hasattr(e, 'status_code'): api_guard.report_error(e.status_code)
            return None

    async def analyze_and_trade(self, symbol: str, live_data=None, **kwargs):
        print(f"🔍 [SCANNER] جاري فحص {symbol} (Request Weight: {api_guard.current_weight}/{api_guard.max_weight})...")
        async with AsyncSessionLocal() as session:
            cfg_res = await session.execute(select(UserConfig).where(UserConfig.telegram_id == self.chat_id))
            cfg = cfg_res.scalars().first()
            if not cfg or not cfg.is_active or cfg.emergency_stop: return
            
            coin_res = await session.execute(select(TrackedCoin).where(TrackedCoin.symbol == symbol))
            coin = coin_res.scalars().first()
            if not coin or not coin.enabled: return

            try:
                hist_key = f"hist_cache_{symbol}_{coin.timeframe}"
                ohlcv = redis_client.get_data(hist_key)
                
                if not ohlcv:
                    await api_guard.check_wait(1)
                    try:
                        ohlcv = await self.exchange.fetch_ohlcv(symbol, coin.timeframe, limit=100)
                        api_guard.update_weight(self.exchange.last_response_headers.get('X-MBX-USED-WEIGHT-1M', 0))
                        redis_client.set_data(hist_key, ohlcv, ex=3600)
                    except Exception as e:
                        if hasattr(e, 'status_code'): api_guard.report_error(e.status_code)
                        return
                
                df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
                
                if live_data:
                    new_row = [datetime.now().timestamp()*1000, live_data['o'], live_data['h'], live_data['l'], live_data['c'], live_data['v']]
                    df.iloc[-1] = new_row
                    print(f"⚡ [CACHE] تم استخدام بيانات WebSocket الحية لـ {symbol}")
            except Exception as e:
                print(f"⚠️ [SCANNER ERROR] Error processing OHLCV for {symbol}: {e}")
                return
            
            # 1. تحليل الاستراتيجيات الفنية
            df_higher = await self.get_higher_timeframe_data(symbol, coin.timeframe)
            params = self.strategies.get_trade_params(df)
            
            # 2. Decision Engine: SMC, Volume, Context
            smc_data = self.smc_engine.detect_structure(df)
            pd_zones = self.smc_engine.get_premium_discount(df)
            liq_data = self.smc_engine.detect_liquidity(df)
            vol_data = self.volume_engine.get_volume_bias(df)
            global_context = await self.market_context.get_market_correlations()
            higher_regime = self.market_context.detect_market_regime(df_higher) if df_higher is not None else "UNKNOWN"
            
            total_score = 0
            decision_report = []
            
            if not liq_data['liquidity_sweep']:
                total_score -= 20
                decision_report.append("Waiting for Liquidity Sweep")
            else:
                total_score += 25
                decision_report.append("Liquidity Sweep Detected")

            if smc_data['state'] in ["BOS_UP", "CHoCH_UP"]:
                total_score += 30
                decision_report.append(f"Structure Shift: {smc_data['state']}")
            
            if pd_zones['zone'] == "DISCOUNT":
                total_score += 15
                decision_report.append("Discount Zone")
            else:
                total_score -= 15
                decision_report.append("Premium Zone")

            if vol_data['bias'] == "AGGRESSIVE_BUYING":
                total_score += 20
                decision_report.append("Institutional Buying Pressure")
            
            if global_context['btc_bias'] == "BULLISH":
                total_score += 10
            elif global_context['btc_bias'] == "BEARISH":
                total_score -= 30
                decision_report.append("Global Market Bias: Bearish")

            if higher_regime == "TRENDING_DOWN" and smc_data['state'] == "CHoCH_UP":
                total_score -= 25
                decision_report.append("Conflict: Counter-Trend")

            total_score = max(0, total_score)
            current_session = self.get_trading_session()
            prob = await self.calculate_probability(symbol, total_score, current_session)

            # تسجيل صفقة ظل
            new_shadow = ShadowTrade(
                symbol=symbol, score=total_score, entry_price=params["entry"],
                stop_loss=params["sl"], take_profit=params["tp"],
                trading_session=current_session, probability_score=prob,
                reasoning_report=" | ".join(decision_report)
            )
            session.add(new_shadow)
            await session.commit()
            print(f"📝 [SHADOW] تسجيل صفقة ظل لـ {symbol} (Prob: {prob:.1f}%)")

            # الفلترة للـ Live
            if total_score < 70:
                print(f"⏭️ [SCANNER] {symbol} لم يجتز المعايير (Score: {total_score:.1f}).")
                return

            # حماية الارتباط
            open_trades_res = await session.execute(select(LiveTrade).where(LiveTrade.status == "OPEN"))
            open_trades = open_trades_res.scalars().all()
            if any(t.symbol == symbol for t in open_trades): return
            if not self.risk_manager.check_correlation_risk(open_trades, symbol):
                print(f"🚫 [RISK] تم رفض {symbol} بسبب الارتباط العالي.")
                return

            # تنفيذ الصفقة
            risk_amount = coin.capital * (coin.risk_percentage / 100)
            sl_dist = abs(params["entry"] - params["sl"])
            if sl_dist <= 0: return
            amount = risk_amount / (sl_dist / params["entry"])
            
            print(f"🚀 [EXECUTION] بناء صفقة {symbol} (Amount: {amount:.2f} USDT)...")
            new_live = LiveTrade(
                symbol=symbol, type="BUY", entry_price=params["entry"], stop_loss=params["sl"],
                take_profit=params["tp"], amount=amount, score=total_score,
                entry_reason=" | ".join(decision_report)
            )
            session.add(new_live)
            await session.commit()
            print(f"✅ [SUCCESS] تم تفعيل الصفقة الحقيقية لـ {symbol} بنجاح.")
