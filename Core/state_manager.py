import asyncio
import logging
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
            cls._instance.min_warmup_sec = 30 # هذا لم يعد يستخدم بشكل مباشر للانتظار الثابت
            cls._instance.data_threshold = 5 # Minimum data points (e.g., kline keys) before ready, adjusted for single kline dict
        return cls._instance

    def set_state(self, new_state: SystemState):
        logger.info(f"🔄 [STATE] Transition: {self.state.value} -> {new_state.value}")
        self.state = new_state

    def is_ready(self):
        return self.state == SystemState.READY

    async def is_cache_warmed_up(self):
        from database import AsyncSessionLocal, TrackedCoin
        from Core.redis_manager import redis_client

        async with AsyncSessionLocal() as session:
            coins_res = await session.execute(select(TrackedCoin).where(TrackedCoin.enabled == True))
            symbols = [c.symbol.strip() for c in coins_res.scalars().all() if c.symbol and c.symbol.strip()]
        
        if not symbols: # No symbols to track, consider warmed up
            return True

        for symbol in symbols:
            kline_data = redis_client.get_data(f"live_klines_{symbol}") # Assuming klines are stored per symbol
            # Check if kline_data exists and is a dictionary with expected keys
            # Assuming a single kline dict is stored, not a list of klines
            if not isinstance(kline_data, dict) or not all(key in kline_data for key in ["o", "h", "l", "c", "v", "x"]):
                logger.info(f"⏳ [WARMUP] {symbol} لا يزال يحتاج إلى بيانات إضافية في الكاش. (الحد الأدنى: {self.data_threshold})")
                return False
        logger.info("✅ [WARMUP] الكاش مكتمل لجميع الرموز المطلوبة.")
        return True

    async def wait_for_ready(self):
        while not self.is_ready():
            await asyncio.sleep(1)

state_manager = StateManager()
