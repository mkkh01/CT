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
        self._analysis_locks = {} # أقفال لمنع تراكب التحليل لكل رمز
        self._last_analysis_time = {} # تتبع وقت آخر تحليل لكل رمز

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
            # عند حدوث 418/429، نرفع استثناء فوراً لإنهاء المهمة الحالية ومنع Retries المتوازية
            raise Exception(f"BANNED: Binance 418/429 detected. Waiting {retry_after}s.")
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
        
        # 1. Circuit Breaker: تحقق من الحظر العالمي قبل البدء
        if rate_limiter.is_banned:
            remaining = rate_limiter.ban_until - time.time()
            if remaining > 0:
                raise Exception(f"CIRCUIT BREAKER: REST calls are globally paused for {remaining:.1f}s")

        # Diagnostic Log: قبل الاستدعاء
        print(f"📡 [API CALL] {source} -> {func.__name__}({symbol}, {timeframe}, {kwargs})")
        
        start_time = time.time()
        for attempt in range(5):
            try:
                # تحقق مرة أخرى داخل الحلقة (في حال تم الحظر بواسطة Task أخرى)
                if rate_limiter.is_banned and (rate_limiter.ban_until - time.time()) > 0:
                    raise Exception("CIRCUIT BREAKER: REST calls paused by another task")

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
        """جلب بيانات الإطار الزمني الأعلى مع نظام التخزين المؤقت الذكي"""
        tf_map = {"5m": "15m", "15m": "1h", "30m": "4h", "1h": "4h", "4h": "1d"}
        higher_tf = tf_map.get(current_tf, "1d")
        cache_key = f"htf_{symbol}_{higher_tf}"
        
        # 1. التحقق من الكاش المنظم (Redis)
        cached_ohlcv = self.redis.get_data(cache_key)
        if cached_ohlcv:
            # التحقق من حداثة البيانات (هل آخر شمعة قريبة من الوقت الحالي؟)
            last_ts = cached_ohlcv[-1][0]
            now_ms = time.time() * 1000
            tf_ms = {"15m": 900000, "1h": 3600000, "4h": 14400000, "1d": 86400000}.get(higher_tf, 3600000)
            
            if (now_ms - last_ts) < (tf_ms * 1.5): # الكاش لا يزال طازجاً
                log_api_request(symbol, higher_tf, "HTF_CACHE_HIT", from_cache=True)
                return pd.DataFrame(cached_ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])

        # 2. إذا كان الكاش مفقوداً أو قديماً، نجلب من REST ولكن بـ Lock صارم
        lock = await self.redis.get_lock(f"lock_{cache_key}")
        async with lock:
            # Double-check بعد الحصول على القفل
            cached_ohlcv = self.redis.get_data(cache_key)
            if cached_ohlcv:
                last_ts = cached_ohlcv[-1][0]
                if (time.time() * 1000 - last_ts) < (tf_ms * 1.5):
                    return pd.DataFrame(cached_ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])

            try:
                print(f"📥 [HTF] تحديث بيانات الإطار الأعلى {higher_tf} لـ {symbol} من REST...")
                ohlcv = await self._safe_api_call(self.exchange.fetch_ohlcv, symbol, higher_tf, limit=100, source="HTF_REST")
                if ohlcv:
                    # تخزين لفترة أطول للإطارات العليا (ساعتان بدلاً من ساعة)
                    self.redis.set_data(cache_key, ohlcv, ttl=7200) 
                    return pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            except Exception as e:
                print(f"⚠️ [HTF] فشل جلب HTF لـ {symbol}: {e}")
                # في حالة الفشل، نحاول استخدام الكاش القديم إذا وجد بدلاً من الفشل التام
                if cached_ohlcv:
                    return pd.DataFrame(cached_ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
                return None
        return None

    async def analyze_and_trade(self, symbol: str, **kwargs):
        # 0. نظام Single-flight لكل رمز: منع تداخل مهام التحليل لنفس الرمز
        if symbol not in self._analysis_locks:
            self._analysis_locks[symbol] = asyncio.Lock()
        
        if self._analysis_locks[symbol].locked():
            # إذا كان هناك تحليل قيد التنفيذ، نتخطى المهمة الجديدة تماماً
            return

        async with self._analysis_locks[symbol]:
            # التحقق من الوقت منذ آخر تحليل (منع التكرار السريع)
            now_ts = time.time()
            # إذا تم التحليل قبل أقل من 60 ثانية، نتخطى أي طلب جديد (سواء من Scanner أو WebSocket)
            if symbol in self._last_analysis_time and (now_ts - self._last_analysis_time[symbol]) < 60:
                return

            # تتبع عدد المهام المتزامنة عالمياً (للتشخيص فقط)
            active_tasks = sum(1 for lock in self._analysis_locks.values() if lock.locked())
            # التحقق من حالة الحظر العالمي في السجلات
            ban_status = f" | 🚫 BANNED ({rate_limiter.ban_until - time.time():.1f}s)" if rate_limiter.is_banned else ""
            print(f"📊 [SYSTEM] تحليل نشط لـ {symbol} | إجمالي المهام: {active_tasks}{ban_status}")

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
                        # 2.1 محاولة استخدام بيانات WebSocket المتراكمة إذا كانت كافية (Stale Cache Guard)
                        # هذا يقلل الاعتماد على REST عند إعادة التشغيل إذا كانت البيانات موجودة في Redis
                        lock = await self.redis.get_lock(hist_key)
                        async with lock:
                            ohlcv = self.redis.get_data(hist_key)
                            if not ohlcv:
                                # جلب من REST فقط عند الضرورة القصوى (Cache Miss الحقيقي)
                                print(f"📥 [BINANCE API] جلب بيانات تاريخية أولية لـ {symbol} من REST...")
                                ohlcv = await self._safe_api_call(self.exchange.fetch_ohlcv, symbol, coin.timeframe, limit=250, source="HIST_REST")
                                if ohlcv:
                                    # TTL أطول للبيانات التاريخية (3 أيام بدلاً من يوم واحد) لأنها ثابتة نسبياً
                                    self.redis.set_data(hist_key, ohlcv, ttl=259200) 
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
                
                # تحديث وقت آخر تحليل ناجح
                self._last_analysis_time[symbol] = time.time()
                
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
