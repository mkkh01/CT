import asyncio
import logging
import time
import httpx
from enum import Enum
from sqlalchemy import select

logger = logging.getLogger(__name__)

class SystemState(Enum):
    INIT = "INIT"
    WARMING_UP = "WARMING_UP"
    READY = "READY"
    ERROR = "ERROR"

class StateManager:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(StateManager, cls).__new__(cls)
            cls._instance.state = SystemState.INIT
            cls._instance.cache_lock = asyncio.Lock()
            cls._instance.startup_time = None
            cls._instance.min_warmup_sec = 30
            cls._instance.data_threshold = 50 
        return cls._instance

    def set_state(self, new_state: SystemState):
        logger.info(f"🔄 [STATE] Transition: {self.state.value} -> {new_state.value}")
        self.state = new_state

    def is_ready(self):
        return self.state == SystemState.READY

    async def fetch_historical_data(self, symbol, timeframe):
        from Core.api_guard import api_guard
        from Core.redis_manager import redis_client
        
        await api_guard.check_wait(1)
        url = f"https://api.binance.com/api/v3/klines?symbol={symbol.upper()}&interval={timeframe}&limit=100"
        
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(url, timeout=10)
                if response.status_code == 200:
                    klines = response.json()
                    formatted_data = [
                        [k[0], float(k[1]), float(k[2]), float(k[3]), float(k[4]), float(k[5])]
                        for k in klines
                    ]
                    hist_key = f"hist_cache_{symbol}_{timeframe}"
                    await redis_client.set_data(hist_key, formatted_data)
                    logger.info(f"✅ [HISTORY] تم جلب {len(formatted_data)} شمعة لـ {symbol} ({timeframe})")
                    return True
                else:
                    api_guard.report_error(response.status_code)
                    logger.error(f"❌ [HISTORY] فشل جلب البيانات لـ {symbol}: {response.status_code}")
                    return False
        except Exception as e:
            logger.error(f"❌ [HISTORY] خطأ أثناء جلب البيانات لـ {symbol}: {e}")
            return False

    async def is_cache_warmed_up(self):
        from database import AsyncSessionLocal, TrackedCoin
        from Core.redis_manager import redis_client

        async with AsyncSessionLocal() as session:
            coins_res = await session.execute(select(TrackedCoin).where(TrackedCoin.enabled == True))
            coins = coins_res.scalars().all()
            symbols = [c.symbol.strip() for c in coins if c.symbol and c.symbol.strip()]
        
        if not symbols:
            return True

        all_warmed = True
        for coin in coins:
            symbol = coin.symbol.strip()
            timeframe = coin.timeframe
            
            hist_key = f"hist_cache_{symbol}_{timeframe}"
            hist_data = redis_client.get_data(hist_key)
            if not hist_data or len(hist_data) < self.data_threshold:
                logger.info(f"⏳ [WARMUP] جلب بيانات تاريخية لـ {symbol}...")
                success = await self.fetch_historical_data(symbol, timeframe)
                if not success:
                    all_warmed = False
                    continue
            
            kline_data = redis_client.get_data(f"live_klines_{symbol}")
            if not isinstance(kline_data, dict) or not all(key in kline_data for key in ["o", "h", "l", "c", "v", "x"]):
                # محاولة تعبئة بيانات لايف أولية من البيانات التاريخية إذا لم تصل بيانات WebSocket بعد
                # لتجنب التوقف اللانهائي في مرحلة الـ Warmup
                hist_data = redis_client.get_data(hist_key)
                if hist_data and len(hist_data) > 0:
                    last_k = hist_data[-1]
                    # محاكاة هيكل بيانات WebSocket
                    initial_live = {
                        'o': last_k[1], 'h': last_k[2], 'l': last_k[3], 
                        'c': last_k[4], 'v': last_k[5], 'x': True
                    }
                    await redis_client.set_data(f"live_klines_{symbol}", initial_live)
                    logger.info(f"⚡ [WARMUP] تم استخدام آخر شمعة تاريخية كبيانات أولية لـ {symbol}")
                else:
                    logger.info(f"⏳ [WARMUP] {symbol} بانتظار أول شمعة حية...")
                    all_warmed = False
                
        return all_warmed

    async def wait_for_ready(self):
        while not self.is_ready():
            await asyncio.sleep(1)

state_manager = StateManager()
