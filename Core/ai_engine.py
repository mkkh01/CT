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
from Core.redis_manager import redis_client
from Core.state_manager import state_manager

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
                    return
                
                if not live_data or len(ohlcv) < state_manager.data_threshold:
                    return
                
                # إنشاء DataFrame مع تحديد أنواع البيانات لتجنب التحذيرات
                df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
                df = df.astype({'timestamp': 'float64', 'open': 'float64', 'high': 'float64', 'low': 'float64', 'close': 'float64', 'volume': 'float64'})
                
                if live_data:
                    new_row = [float(datetime.now().timestamp()*1000), float(live_data['o']), float(live_data['h']), float(live_data['l']), float(live_data['c']), float(live_data['v'])]
                    df.iloc[-1] = new_row
            except Exception as e:
                print(f"⚠️ [SCANNER ERROR] Error processing OHLCV for {symbol}: {e}")
                return
            
            # 1. تحليل الاستراتيجيات الفنية
            df_higher = await self.get_higher_timeframe_data(symbol, coin.timeframe)
            params = self.strategies.get_trade_params(df)
            
            # 2. Decision Engine
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

            new_shadow = ShadowTrade(
                symbol=symbol, score=total_score, entry_price=params["entry"],
                stop_loss=params["sl"], take_profit=params["tp"],
                trading_session=current_session, probability_score=prob,
                reasoning_report=" | ".join(decision_report)
            )
            session.add(new_shadow)
            await session.commit()

            if total_score < 70:
                return

            open_trades_res = await session.execute(select(LiveTrade).where(LiveTrade.status == "OPEN"))
            open_trades = open_trades_res.scalars().all()
            if any(t.symbol == symbol for t in open_trades): return
            if not self.risk_manager.check_correlation_risk(open_trades, symbol):
                return

            risk_amount = coin.capital * (coin.risk_percentage / 100)
            sl_dist = abs(params["entry"] - params["sl"])
            if sl_dist <= 0: return
            amount = risk_amount / (sl_dist / params["entry"])
            
            new_live = LiveTrade(
                symbol=symbol, type="BUY", entry_price=params["entry"], stop_loss=params["sl"],
                take_profit=params["tp"], amount=amount, score=total_score,
                entry_reason=" | ".join(decision_report)
            )
            session.add(new_live)
            await session.commit()
