import pandas as pd
import ccxt.async_support as ccxt
from database import AsyncSessionLocal, LiveTrade, ShadowTrade, UserConfig, TrackedCoin
from sqlalchemy import select
from strategies import InstitutionalStrategies
from datetime import datetime
import asyncio
import json
import os

class AIEngine:
    def __init__(self, bot=None, chat_id=None):
        self.strategies = InstitutionalStrategies()
        self.bot = bot
        self.chat_id = chat_id
        self.exchange = ccxt.binance({
            'enableRateLimit': True, 
            'options': {'defaultType': 'spot'},
            'timeout': 30000,
        })

    async def get_higher_timeframe_data(self, symbol, current_tf):
        """جلب بيانات الإطار الزمني الأعلى للفلترة (Phase 2)"""
        from Core.redis_client import redis_client
        tf_map = {"5m": "15m", "15m": "1h", "30m": "4h", "1h": "4h", "4h": "1d"}
        higher_tf = tf_map.get(current_tf, "1d")
        
        cache_key = f"htf_{symbol}_{higher_tf}"
        try:
            cached_ohlcv = redis_client.get_data(cache_key)
            if cached_ohlcv:
                return pd.DataFrame(cached_ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])

            for attempt in range(3):
                try:
                    await asyncio.sleep(5 * (attempt + 1))
                    ohlcv = await self.exchange.fetch_ohlcv(symbol, higher_tf, limit=100)
                    break
                except Exception as e:
                    if attempt == 2: raise e
                    await asyncio.sleep(10)
            
            redis_client.set_data(cache_key, ohlcv, ttl=1800)
            return pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        except Exception as e:
            print(f"⚠️ [SYSTEM] HTF Fetch Error for {symbol}: {e}")
            return None

    async def analyze_and_trade(self, symbol: str, **kwargs):
        print(f"🧠 [SYSTEM] جاري التحليل المؤسسي لـ {symbol}...")
        
        async with AsyncSessionLocal() as session:
            # 1. جلب إعدادات المستخدم والعملة
            cfg_res = await session.execute(select(UserConfig).where(UserConfig.telegram_id == self.chat_id))
            cfg = cfg_res.scalars().first()
            if not cfg or not cfg.is_active or cfg.emergency_stop: return
            
            coin_res = await session.execute(select(TrackedCoin).where(TrackedCoin.symbol == symbol))
            coin = coin_res.scalars().first()
            if not coin or not coin.enabled: return

            # 2. جلب البيانات من الذاكرة اللحظية (Redis & WebSocket)
            from Core.redis_client import redis_client
            try:
                hist_key = f"hist_{symbol}_{coin.timeframe}"
                ohlcv = redis_client.get_data(hist_key)
                
                if not ohlcv:
                    print(f"📥 [SYSTEM] جلب بيانات تاريخية أولية لـ {symbol}...")
                    for attempt in range(3):
                        try:
                            await asyncio.sleep(5 * (attempt + 1))
                            ohlcv = await self.exchange.fetch_ohlcv(symbol, coin.timeframe, limit=250)
                            break
                        except Exception as e:
                            if attempt == 2: raise e
                            await asyncio.sleep(10)
                    redis_client.set_data(hist_key, ohlcv, ttl=86400)
                
                df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
                
                # فصل الشمعة الحية عن المغلقة
                klines_data = redis_client.get_data("live_klines") or {}
                if symbol in klines_data:
                    k = klines_data[symbol]
                    if k.get('x', False): # شمعة مغلقة
                        last_ts = ohlcv[-1][0]
                        # التأكد من عدم تكرار إضافة نفس الشمعة (استخدام timestamp)
                        # ملاحظة: Binance WebSocket kline timestamp هو وقت بدء الشمعة
                        if k.get('t', 0) > last_ts:
                            new_row = [k['t'], k['o'], k['h'], k['l'], k['c'], k['v']]
                            ohlcv.append(new_row)
                            if len(ohlcv) > 300: ohlcv.pop(0)
                            redis_client.set_data(hist_key, ohlcv, ttl=86400)
                            df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
                    
                    # لا نحدث الشمعة الأخيرة في df إلا إذا أردنا التحليل اللحظي (وهو مرفوض حسب التعليمات)
                    # التعليمات تقول: "القرار النهائي يجب أن يعتمد أساسًا على شموع مغلقة"
                    # لذا سنقوم بحذف الشمعة الأخيرة من df إذا كانت غير مكتملة
                    if not k.get('x', False):
                        # نستخدم البيانات التاريخية (المغلقة) فقط للتحليل
                        df = df[df['timestamp'] < k.get('t', 0)]
            except Exception as e:
                print(f"⚠️ [SYSTEM] خطأ في معالجة بيانات {symbol}: {e}")
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
