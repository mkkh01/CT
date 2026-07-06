import pandas as pd
import ccxt.async_support as ccxt
from database import AsyncSessionLocal, LiveTrade, ShadowTrade, UserConfig, TrackedCoin
from sqlalchemy import select
from strategies import InstitutionalStrategies
from datetime import datetime
import asyncio
import json
import os

from Core.utils import rate_limiter, log_api_request, logger
import time

class AIEngine:
    def __init__(self, bot=None, chat_id=None):
        self.strategies = InstitutionalStrategies()
        self.bot = bot
        self.chat_id = chat_id
        self.exchange = ccxt.binance({
            'enableRateLimit': False, # سنستخدم الـ RateLimiter الخاص بنا للتحكم الأدق
            'options': {'defaultType': 'spot'},
            'timeout': 30000,
        })
        from Core.redis_client import redis_client
        self.redis = redis_client

    async def _handle_binance_error(self, e, attempt):
        error_str = str(e)
        if "418" in error_str or "429" in error_str:
            retry_after = 60 # القيمة الافتراضية
            try:
                # محاولة استخراج وقت الانتظار من الرسالة إذا وجد
                if "retry-after" in error_str.lower():
                    import re
                    match = re.search(r'retry-after:?\s*(\d+)', error_str.lower())
                    if match: retry_after = int(match.group(1))
            except: pass
            
            rate_limiter.set_ban(retry_after)
            print(f"🛑 [BINANCE API] تم تلقي 418/429. حظر جميع الطلبات لـ {retry_after} ثانية.")
            return retry_after
        
        wait_time = min((2 ** attempt) + (0.1 * attempt), 60)
        print(f"⚠️ [BINANCE API] خطأ: {e}. إعادة المحاولة بعد {wait_time:.1f} ثانية...")
        await asyncio.sleep(wait_time)
        return wait_time

    async def _safe_api_call(self, func, *args, **kwargs):
        # استخراج الوسائط الخاصة بالنظام (Internal Metadata)
        symbol = kwargs.pop('symbol', args[0] if args else "Unknown")
        timeframe = kwargs.pop('timeframe', args[1] if len(args) > 1 else "Unknown")
        source = kwargs.pop('source', 'Unknown')
        
        start_time = time.time()
        for attempt in range(5):
            try:
                await rate_limiter.wait_if_needed()
                # الآن kwargs لا تحتوي على source، لذا لن يتم تمريرها إلى CCXT
                result = await func(*args, **kwargs)
                
                execution_time = time.time() - start_time
                log_api_request(symbol, timeframe, source, from_cache=False, execution_time=execution_time, **kwargs)
                
                # تحديث عداد الطلبات في Redis
                current_count = self.redis.get_data("binance_api_calls") or 0
                self.redis.set_data("binance_api_calls", current_count + 1, ttl=86400)
                
                return result
            except Exception as e:
                if attempt == 4:
                    print(f"❌ [BINANCE API] فشل نهائي بعد 5 محاولات: {e}")
                    raise e
                await self._handle_binance_error(e, attempt)

    async def get_higher_timeframe_data(self, symbol, current_tf):
        """جلب بيانات الإطار الزمني الأعلى مع نظام التخزين المؤقت ومنع الطلبات المتوازية"""
        tf_map = {"5m": "15m", "15m": "1h", "30m": "4h", "1h": "4h", "4h": "1d"}
        higher_tf = tf_map.get(current_tf, "1d")
        cache_key = f"htf_{symbol}_{higher_tf}"
        
        # 1. التحقق من الكاش أولاً
        cached_ohlcv = self.redis.get_data(cache_key)
        if cached_ohlcv:
            log_api_request(symbol, higher_tf, "HTF_FETCH", from_cache=True)
            return pd.DataFrame(cached_ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])

        # 2. استخدام Lock لمنع الطلبات المتوازية لنفس البيانات
        lock = await self.redis.get_lock(cache_key)
        async with lock:
            # التحقق مرة أخرى بعد الحصول على الـ Lock (Double-Checked Locking)
            cached_ohlcv = self.redis.get_data(cache_key)
            if cached_ohlcv:
                log_api_request(symbol, higher_tf, "HTF_FETCH_LOCKED", from_cache=True)
                return pd.DataFrame(cached_ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])

            try:
                ohlcv = await self._safe_api_call(self.exchange.fetch_ohlcv, symbol, higher_tf, limit=100, source="HTF_REST")
                if ohlcv:
                    self.redis.set_data(cache_key, ohlcv, ttl=3600) # تخزين لمدة ساعة
                    return pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            except:
                return None
        return None

    async def analyze_and_trade(self, symbol: str, **kwargs):
        async with AsyncSessionLocal() as session:
            # 1. جلب إعدادات المستخدم والعملة
            cfg_res = await session.execute(select(UserConfig).where(UserConfig.telegram_id == self.chat_id))
            cfg = cfg_res.scalars().first()
            if not cfg or not cfg.is_active or cfg.emergency_stop: return
            
            coin_res = await session.execute(select(TrackedCoin).where(TrackedCoin.symbol == symbol))
            coin = coin_res.scalars().first()
            if not coin or not coin.enabled: return

            print(f"🧠 [ANALYSIS] جاري التحليل المؤسسي لـ {symbol} ({coin.timeframe})...")

            # 2. جلب البيانات من الذاكرة اللحظية (Redis & WebSocket)
            try:
                hist_key = f"hist_{symbol}_{coin.timeframe}"
                ohlcv = self.redis.get_data(hist_key)
                
                if not ohlcv:
                    lock = await self.redis.get_lock(hist_key)
                    async with lock:
                        ohlcv = self.redis.get_data(hist_key)
                        if not ohlcv:
                            print(f"📥 [BINANCE API] جلب بيانات تاريخية أولية لـ {symbol}...")
                            ohlcv = await self._safe_api_call(self.exchange.fetch_ohlcv, symbol, coin.timeframe, limit=250, source="HIST_REST")
                            if ohlcv:
                                self.redis.set_data(hist_key, ohlcv, ttl=86400)
                            else:
                                print(f"❌ [ANALYSIS] تعذر الحصول على بيانات لـ {symbol}. تخطي التحليل.")
                                return
                else:
                    log_api_request(symbol, coin.timeframe, "HIST_FETCH", from_cache=True)
                
                if not ohlcv or len(ohlcv) == 0:
                    print(f"❌ [ANALYSIS] بيانات OHLCV فارغة تماماً لـ {symbol}.")
                    return

                df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
                
                # دمج الشمعة الحية من WebSocket إذا لزم الأمر
                klines_data = self.redis.get_data("live_klines") or {}
                if symbol in klines_data:
                    k = klines_data[symbol]
                    if k.get('x', False): # شمعة مغلقة
                        last_ts = ohlcv[-1][0]
                        if k.get('t', 0) > last_ts:
                            print(f"📥 [DATA] إضافة شمعة مغلقة جديدة من WebSocket لـ {symbol} (TS: {k['t']})")
                            new_row = [k['t'], k['o'], k['h'], k['l'], k['c'], k['v']]
                            ohlcv.append(new_row)
                            if len(ohlcv) > 300: ohlcv.pop(0)
                            self.redis.set_data(hist_key, ohlcv, ttl=86400)
                            df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
                    
                    # منع تحليل الشمعة الحية (غير المكتملة)
                    if not k.get('x', False):
                        df = df[df['timestamp'] < k.get('t', 10**15)]
                
                if len(df) < 100:
                    print(f"❌ [ANALYSIS] البيانات المغلقة لـ {symbol} غير كافية (الطول: {len(df)}).")
                    return
                
                # Debug: التأكد من حداثة البيانات
                last_candle_time = datetime.fromtimestamp(df['timestamp'].iloc[-1] / 1000)
                print(f"🔍 [DEBUG] آخر شمعة لـ {symbol}: {last_candle_time} | عدد الشموع: {len(df)}")

            except Exception as e:
                print(f"⚠️ [SYSTEM] خطأ غير متوقع في معالجة بيانات {symbol}: {e}")
                return
            
            # 3. تحليل الإطار الزمني الأعلى (Filter)
            df_higher = await self.get_higher_timeframe_data(symbol, coin.timeframe)
            
            # 4. نظام التقييم (Scoring Engine)
            analysis = self.strategies.calculate_combined_score(df, df_higher)
            total_score = analysis["total_score"]
            
            # تسجيل صفقة ظل (Shadow Trade) دائماً للتعلم (Phase 8)
            new_shadow = ShadowTrade(
                symbol=symbol,
                indicators_snapshot=analysis,
                market_state=analysis["market_state"],
                score=total_score
            )
            session.add(new_shadow)
            await session.commit()

            # 5. الفلترة الصارمة (نرفع الحد الأدنى لضمان الجودة)
            if total_score < 75 or analysis["quality_score"] < 60:
                print(f"🚫 [VALIDATION] تم رفض {symbol}: النقاط {total_score}, الجودة {analysis['quality_score']}")
                return

            # 6. تنفيذ الصفقة الحقيقية (Live Trade)
            params = self.strategies.get_trade_params(df)
            
            # فلترة المخاطرة (R:R Check)
            if params["rr"] < 1.5:
                print(f"🚫 [RISK] تم رفض {symbol}: نسبة العائد للمخاطرة ضعيفة {params['rr']}")
                return

            # حساب حجم الصفقة (Risk Engine)
            risk_amount = coin.capital * (coin.risk_percentage / 100)
            sl_pct = abs(params["entry"] - params["sl"]) / params["entry"]
            amount = risk_amount / sl_pct if sl_pct > 0 else 0
            
            if amount <= 0 or amount > coin.capital * 2: # حماية من الرافعة المالية المفرطة
                print(f"🚫 [RISK] حجم صفقة غير منطقي لـ {symbol}: {amount}")
                return

            # التأكد من عدم وجود صفقة مفتوحة
            check = await session.execute(select(LiveTrade).where((LiveTrade.symbol == symbol) & (LiveTrade.status == "OPEN")))
            if check.scalars().first(): 
                print(f"⏳ [SYSTEM] توجد صفقة مفتوحة بالفعل لـ {symbol}")
                return

            new_live = LiveTrade(
                symbol=symbol,
                type="BUY",
                entry_price=params["entry"],
                stop_loss=params["sl"],
                take_profit=params["tp"],
                amount=amount,
                score=total_score,
                entry_reason=analysis["report"],
                market_state=analysis["market_state"],
                # إضافة بيانات إضافية للتشخيص
                indicators_snapshot={
                    "rr": params["rr"],
                    "atr": params["atr"],
                    "quality": analysis["quality_score"],
                    "timestamp": datetime.now().isoformat()
                }
            )
            session.add(new_live)
            await session.commit()
            
            print(f"🚀 [EXECUTION] تم فتح صفقة مؤسسية لـ {symbol} بنقاط {total_score}")
            if self.bot:
                msg = (f"🚀 *صفقة مؤسسية جديدة*\n"
                       f"━━━━━━━━━━━━━━\n"
                       f"🪙 العملة: #{symbol}\n"
                       f"🎯 النقاط: {total_score}/100\n"
                       f"💰 الدخول: `{params['entry']}`\n"
                       f"🛡️ الوقف: `{params['sl']}`\n"
                       f"🏁 الهدف: `{params['tp']}`\n"
                       f"━━━━━━━━━━━━━━\n"
                       f"📊 السبب: {analysis['report']}")
                await self.bot.send_message(self.chat_id, msg, parse_mode='Markdown')
