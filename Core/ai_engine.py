import pandas as pd
import ccxt.async_support as ccxt
from database import AsyncSessionLocal, LiveTrade, ShadowTrade, UserConfig, TrackedCoin
from sqlalchemy import select
from strategies import InstitutionalStrategies
from datetime import datetime
import asyncio
import json
import os
import time

from Core.utils import rate_limiter, diag_logger, log_api_request

class AIEngine:
    def __init__(self, bot=None, chat_id=None):
        self.strategies = InstitutionalStrategies()
        self.bot = bot
        self.chat_id = chat_id
        self.exchange = ccxt.binance({
            'enableRateLimit': False,
            'options': {'defaultType': 'spot'},
            'timeout': 30000,
        })
        from Core.redis_client import redis_client
        self.redis = redis_client
        self._analysis_locks = {}
        self._last_analysis_time = {}

    async def _handle_binance_error(self, e, attempt):
        error_str = str(e)
        if "418" in error_str or "429" in error_str:
            retry_after = 60
            try:
                if "retry-after" in error_str.lower():
                    import re
                    match = re.search(r'retry-after:?\s*(\d+)', error_str.lower())
                    if match: retry_after = int(match.group(1))
            except: pass
            rate_limiter.set_ban(retry_after)
            diag_logger.system(f"BANNED: Binance 418/429 detected", retry_after=retry_after)
            raise Exception(f"BANNED: Binance 418/429 detected. Waiting {retry_after}s.")
        
        wait_time = min((2 ** attempt) + (0.1 * attempt), 60)
        await asyncio.sleep(wait_time)
        return wait_time

    async def _safe_api_call(self, func, *args, **kwargs):
        symbol = kwargs.pop('symbol', args[0] if args else "Unknown")
        timeframe = kwargs.pop('timeframe', args[1] if len(args) > 1 else "Unknown")
        source = kwargs.pop('source', 'Unknown')
        
        if rate_limiter.is_banned:
            remaining = rate_limiter.ban_until - time.time()
            if remaining > 0:
                raise Exception(f"CIRCUIT BREAKER: REST calls paused for {remaining:.1f}s")

        start_time = time.time()
        for attempt in range(5):
            try:
                if rate_limiter.is_banned and (rate_limiter.ban_until - time.time()) > 0:
                    raise Exception("CIRCUIT BREAKER: REST calls paused by another task")

                await rate_limiter.wait_if_needed()
                result = await func(*args, **kwargs)
                exec_time = time.time() - start_time
                return result, exec_time, False # result, time, from_cache
            except Exception as e:
                if attempt == 4: raise e
                await self._handle_binance_error(e, attempt)

    async def get_higher_timeframe_data(self, symbol, current_tf):
        tf_map = {"5m": "15m", "15m": "1h", "30m": "4h", "1h": "4h", "4h": "1d"}
        higher_tf = tf_map.get(current_tf, "1d")
        cache_key = f"htf_{symbol}_{higher_tf}"
        
        cached_ohlcv = self.redis.get_data(cache_key)
        if cached_ohlcv:
            last_ts = cached_ohlcv[-1][0]
            now_ms = time.time() * 1000
            tf_ms = {"15m": 900000, "1h": 3600000, "4h": 14400000, "1d": 86400000}.get(higher_tf, 3600000)
            if (now_ms - last_ts) < (tf_ms * 1.5):
                return pd.DataFrame(cached_ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume']), 0, True
        
        lock = await self.redis.get_lock(f"lock_{cache_key}")
        async with lock:
            cached_ohlcv = self.redis.get_data(cache_key)
            if cached_ohlcv:
                last_ts = cached_ohlcv[-1][0]
                if (time.time() * 1000 - last_ts) < (tf_ms * 1.5):
                    return pd.DataFrame(cached_ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume']), 0, True

            try:
                ohlcv, exec_time, _ = await self._safe_api_call(self.exchange.fetch_ohlcv, symbol, higher_tf, limit=100, source="HTF_REST")
                if ohlcv:
                    self.redis.set_data(cache_key, ohlcv, ttl=7200) 
                    return pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume']), exec_time, False
            except:
                if cached_ohlcv: return pd.DataFrame(cached_ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume']), 0, True
                return None, 0, False
        return None, 0, False

    async def analyze_and_trade(self, symbol: str, **kwargs):
        if symbol not in self._analysis_locks:
            self._analysis_locks[symbol] = asyncio.Lock()
        
        if self._analysis_locks[symbol].locked(): return

        async with self._analysis_locks[symbol]:
            now_ts = time.time()
            if symbol in self._last_analysis_time and (now_ts - self._last_analysis_time[symbol]) < 60:
                return

            async with AsyncSessionLocal() as session:
                cfg_res = await session.execute(select(UserConfig).where(UserConfig.telegram_id == self.chat_id))
                cfg = cfg_res.scalars().first()
                if not cfg or not cfg.is_active or cfg.emergency_stop: return
                
                coin_res = await session.execute(select(TrackedCoin).where(TrackedCoin.symbol == symbol))
                coin = coin_res.scalars().first()
                if not coin or not coin.enabled: return

                # Phase 1: Data Fetching
                data_info = {"source": "Binance", "count": 0, "load_time": datetime.now().strftime('%H:%M:%S'), "exec_time": 0}
                try:
                    hist_key = f"hist_{symbol}_{coin.timeframe}"
                    ohlcv = self.redis.get_data(hist_key)
                    from_cache = True
                    exec_time = 0
                    
                    if not ohlcv:
                        lock = await self.redis.get_lock(hist_key)
                        async with lock:
                            ohlcv = self.redis.get_data(hist_key)
                            if not ohlcv:
                                ohlcv, exec_time, from_cache = await self._safe_api_call(self.exchange.fetch_ohlcv, symbol, coin.timeframe, limit=250, source="HIST_REST")
                                if ohlcv: self.redis.set_data(hist_key, ohlcv, ttl=259200)
                                else: 
                                    data_info["error"] = "Failed to fetch OHLCV"
                                    diag_logger.data_phase(data_info)
                                    return
                    
                    df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
                    data_info.update({
                        "source": "Cache" if from_cache else "Binance",
                        "count": len(df),
                        "last_candle": datetime.fromtimestamp(df['timestamp'].iloc[-1] / 1000).strftime('%Y-%m-%d %H:%M:%S'),
                        "missing": len(df) < 250,
                        "has_nan": df.isnull().values.any(),
                        "has_duplicate": df['timestamp'].duplicated().any(),
                        "exec_time": exec_time
                    })
                    diag_logger.data_phase(data_info)
                    
                    # Debug Mode Warning
                    if df['close'].iloc[-1] == 0:
                        diag_logger.warning("Price is zero!", "Critical data error", "AIEngine.analyze_and_trade")

                except Exception as e:
                    data_info["error"] = str(e)
                    diag_logger.data_phase(data_info)
                    return

                # Phase 2-9: Strategy Analysis
                df_higher, htf_exec, htf_cache = await self.get_higher_timeframe_data(symbol, coin.timeframe)
                analysis = self.strategies.calculate_combined_score(df, df_higher)
                
                # Execution of Logs
                diag_logger.market_regime_phase(analysis["regime_data"])
                diag_logger.htf_filter_phase(analysis["htf_data"])
                diag_logger.indicators_phase(analysis["indicators_data"])
                diag_logger.smart_money_phase(analysis["smc_data"])
                diag_logger.strategy_validation_phase(analysis["validation_data"])
                diag_logger.score_engine_phase(analysis["score_data"])
                diag_logger.rejection_reasons_phase(analysis["rejection_data"])
                diag_logger.quality_phase(analysis["quality_data"])

                # Phase 10: Final Decision
                params = self.strategies.get_trade_params(df)
                decision_data = {
                    "verdict": analysis["verdict"],
                    "confidence": analysis["confidence"],
                    "probability": analysis["probability"],
                    "risk_pct": params["risk_pct"],
                    "rr": params["rr"],
                    "reason": " | ".join(analysis["reasons"]) if analysis["reasons"] else "No specific positive reasons"
                }
                diag_logger.final_decision_phase(decision_data)

                # Phase 3: Shadow Trade
                new_shadow = ShadowTrade(
                    symbol=symbol,
                    indicators_snapshot=analysis,
                    market_state=analysis["regime_data"]["state"],
                    score=analysis["total_score"]
                )
                session.add(new_shadow)
                await session.commit()

                if analysis["verdict"] == "SKIP": return

                # Final Checks before Live Execution
                if params["rr"] < 1.5:
                    diag_logger.warning("Low Risk Reward", f"RR is {params['rr']} which is below 1.5", "Execution Phase")
                    return

                risk_amount = coin.capital * (coin.risk_percentage / 100)
                sl_pct = abs(params["entry"] - params["sl"]) / params["entry"]
                amount = risk_amount / sl_pct if sl_pct > 0 else 0
                
                check = await session.execute(select(LiveTrade).where((LiveTrade.symbol == symbol) & (LiveTrade.status == "OPEN")))
                if check.scalars().first(): return

                new_live = LiveTrade(
                    symbol=symbol, type="BUY", entry_price=params["entry"], stop_loss=params["sl"],
                    take_profit=params["tp"], amount=amount, score=analysis["total_score"],
                    entry_reason=decision_data["reason"], market_state=analysis["regime_data"]["state"]
                )
                session.add(new_live)
                await session.commit()
                
                self._last_analysis_time[symbol] = time.time()
                diag_logger.system(f"🚀 OPEN TRADE: {symbol}", price=params['entry'], score=analysis["total_score"])

                if self.bot:
                    msg = (f"🚀 *صفقة مؤسسية جديدة*\n"
                           f"━━━━━━━━━━━━━━\n"
                           f"🪙 العملة: #{symbol}\n"
                           f"🎯 النقاط: {analysis['total_score']}/100\n"
                           f"💰 الدخول: `{params['entry']}`\n"
                           f"🛡️ الوقف: `{params['sl']}`\n"
                           f"🏁 الهدف: `{params['tp']}`\n"
                           f"━━━━━━━━━━━━━━\n"
                           f"📊 الأسباب: {decision_data['reason']}")
                    await self.bot.send_message(self.chat_id, msg, parse_mode='Markdown')
