import pandas as pd
import xgboost as xgb
from database import AsyncSessionLocal, PaperTrade, UserConfig, TrackedCoin
from sqlalchemy import select
from Core.risk_manager import RiskManager
from macro_data import MacroAnalyzer
from strategies import SpotStrategies
import ccxt.async_support as ccxt
import asyncio

class AIEngine:
    def __init__(self, bot=None, chat_id=None):
        self.risk_manager = RiskManager()
        self.macro = MacroAnalyzer()
        self.strategies = SpotStrategies()
        self.model = xgb.XGBClassifier(n_estimators=100, max_depth=3, learning_rate=0.1)
        self.bot = bot
        self.chat_id = chat_id
        self.exchange = ccxt.binance({
            'enableRateLimit': True,
            'options': {'defaultType': 'spot'},
        })

    async def get_coin_config(self, symbol: str):
        """جلب إعدادات العملة المخصصة (رأس المال والإطار الزمني)"""
        # تم تعديل هذا السطر لتعطيل الكاش وحل مشكلة الجمود وخطأ الـ DuplicatePreparedStatement
        async with AsyncSessionLocal(execution_options={"compiled_cache": None}) as session:
            result = await session.execute(select(TrackedCoin).where(TrackedCoin.symbol == symbol))
            return result.scalars().first()

    async def get_candlestick_data(self, symbol: str, timeframe: str, limit: int = 100):
        """جلب بيانات الشموع (candlestick data) من Binance بأمان"""
        try:
            ohlcv = await self.exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
            df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            return df
        except Exception as e:
            print(f"❌ [AI ENGINE] خطأ في جلب بيانات الشموع لـ {symbol}: {e}")
            return pd.DataFrame()

    async def analyze_and_trade(self, symbol: str, current_price: float, atr: float, whale_action: str = None):
        coin_config = await self.get_coin_config(symbol)
        capital = coin_config.allocated_capital if coin_config else 100.0
        timeframe = coin_config.timeframe if coin_config else "15m"
        
        print(f"🔍 [AI ENGINE] ⚡ بدء جولة تحليل ذكية للعملة {symbol} | الإطار: {timeframe} | السعر: {current_price}")
        
        # 1. جلب بيانات الشموع وتأمين الحسابات الفنية
        ohlcv_df = await self.get_candlestick_data(symbol, timeframe)
        
        if ohlcv_df.empty:
            print(f"⚠️ [AI ENGINE] تم إلغاء التحليل لـ {symbol} بسبب فشل جلب الشموع من بينانس.")
            return "HOLD", 50.0

        # تطبيق المؤشرات الفنية وحساب الـ ATR فوراً لتأمين الـ Risk Manager
        ohlcv_df = self.strategies.apply_technical_indicators(ohlcv_df)
        atr = self.strategies.get_atr(ohlcv_df)

        regime = self.macro.get_market_regime()
        fng = self.macro.get_fear_and_greed()
        
        # نقطة الارتكاز لعداد الثقة
        confidence = 50.0  
        signal = "HOLD"

        # 2. تحليل معطيات الماكرو (أوزان مرنة وموزونة ديناميكياً)
        if regime == "RISK_OFF": 
            confidence -= 10.0  
            print("📉 [AI ENGINE] بيئة الماكرو RISK_OFF: خفض الثقة بمقدار -10")
        elif regime == "RISK_ON": 
            confidence += 10.0  
            print("📈 [AI ENGINE] بيئة الماكرو RISK_ON: رفع الثقة بمقدار +10")

        if fng < 25: 
            confidence += 10.0  # منطقة ارتداد تاريخية فرصة شراء
        elif fng > 75: 
            confidence -= 10.0  # منطقة تشبع طمع تاريخية مخاطرة عالية

        # 3. تحليل رادار الحيتان الفوري (وزن حاسم)
        if whale_action == "BUY": 
            confidence += 25.0
            print(f"🐳 [AI ENGINE] رصد تدفق حيتان إيجابي (BUY) لـ {symbol}: رفع الثقة بمقدار +25")
        elif whale_action == "SELL": 
            confidence -= 25.0
            print(f"🐳 [AI ENGINE] رصد تدفق حيتان سلبي (SELL) لـ {symbol}: خفض الثقة بمقدار -25")

        # 4. دمج إشارات التحليل الفني (الاستراتيجيات)
        if self.strategies.check_buy_signal(ohlcv_df):
            confidence += 20.0
            print(f"📊 [AI ENGINE] إشارة فنية صاعدة (BUY SIGNAL) نشطة لـ {symbol}: (+20 ثقة)")
        elif self.strategies.check_sell_signal(ohlcv_df):
            confidence -= 20.0
            print(f"📊 [AI ENGINE] إشارة فنية هابطة (SELL SIGNAL) نشطة لـ {symbol}: (-20 ثقة)")

        print(f"📊 [AI ENGINE] الحصيلة النهائية لعداد الثقة لـ {symbol} هي: ({confidence:.2f}%)")

        # اتخاذ القرار بناءً على عتبات رقمية منطقية وقابلة للتحقيق
        if confidence >= 65.0: 
            signal = "BUY"
        elif confidence <= 35.0: 
            signal = "SELL"

        # تحديد وضوح الصفقة (تظهر للمستخدم أم مخفية للتدريب الذاتي فقط)
        is_visible = confidence >= 80.0 or confidence <= 20.0
