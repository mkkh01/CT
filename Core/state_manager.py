import asyncio
import logging
import httpx
import time
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
            cls._instance.startup_time = time.time()
            cls._instance.min_warmup_sec = 30
            cls._instance.data_threshold = 50 
        return cls._instance

    def set_state(self, new_state: SystemState):
        if self.state != new_state:
            logger.info(f"🔄 [STATE] {self.state.value} -> {new_state.value}")
            self.state = new_state

    def is_ready(self):
        return self.state == SystemState.READY

    async def fetch_historical_data(self, symbol, timeframe):
        from Core.api_guard import api_guard
        from Core.redis_manager import redis_client
        
        # Reduced wait time for warmup to speed up process
        await api_guard.check_wait(0.5)
        url = f"https://api.binance.com/api/v3/klines?symbol={symbol.upper()}&interval={timeframe}&limit=100"
        
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(url, timeout=15)
                if response.status_code == 200:
                    klines = response.json()
                    formatted_data = [
                        [k[0], float(k[1]), float(k[2]), float(k[3]), float(k[4]), float(k[5]), float(k[9])]
                        for k in klines
                    ]
                    hist_key = f"hist_cache_{symbol.lower()}_{timeframe}"
                    await redis_client.set_data(hist_key, formatted_data)
                    logger.debug(f"✅ [WARMUP] Fetched {len(formatted_data)} klines for {symbol}")
                    return True
                else:
                    api_guard.report_error(response.status_code)
                    logger.error(f"❌ [WARMUP] Binance API Error {response.status_code} for {symbol}")
                    return False
        except Exception as e:
            logger.error(f"❌ [WARMUP] Request error for {symbol}: {e}")
            return False

    async def is_cache_warmed_up(self):
        from database import AsyncSessionLocal, TrackedCoin
        from Core.redis_manager import redis_client

        try:
            async with AsyncSessionLocal() as session:
                coins_res = await session.execute(select(TrackedCoin).where(TrackedCoin.enabled == True))
                coins = coins_res.scalars().all()
                symbols = [c.symbol.strip() for c in coins if c.symbol and c.symbol.strip()]
            
            if not symbols: 
                logger.info("ℹ️ [WARMUP] No symbols to warm up.")
                return True

            all_warmed = True
            tasks = []
            
            for coin in coins:
                symbol = coin.symbol.strip().lower()
                timeframe = coin.timeframe
                hist_key = f"hist_cache_{symbol}_{timeframe}"
                
                hist_data = redis_client.get_data(hist_key)
                if not hist_data or len(hist_data) < self.data_threshold:
                    # Execute fetching in sequence to respect API limits but track status
                    success = await self.fetch_historical_data(symbol, timeframe)
                    if not success: all_warmed = False
                
                # Check live data or fill from history
                kline_data = redis_client.get_data(f"live_klines_{symbol}")
                if not isinstance(kline_data, dict) or not all(k in kline_data for k in ["o", "h", "l", "c", "v", "x"]):
                    hist_data = redis_client.get_data(hist_key)
                    if hist_data and len(hist_data) > 0:
                        last_k = hist_data[-1]
                        initial_live = {
                            'o': last_k[1], 'h': last_k[2], 'l': last_k[3], 
                            'c': last_k[4], 'v': last_k[5], 'x': True
                        }
                        await redis_client.set_data(f"live_klines_{symbol}", initial_live)
                    else:
                        all_warmed = False
                        
            return all_warmed
        except Exception as e:
            logger.error(f"❌ [WARMUP ERROR] Critical error in warmup check: {e}")
            return False

    async def wait_for_ready(self, timeout=120):
        """Wait for cache to warm up with a hard timeout"""
        start_time = time.time()
        logger.info(f"🕒 [STATE] Starting warmup (timeout: {timeout}s)...")
        
        while not self.is_ready():
            if await self.is_cache_warmed_up():
                self.set_state(SystemState.READY)
                logger.info("✅ [STATE] Warmup complete. System READY.")
                break
                
            elapsed = time.time() - start_time
            if elapsed > timeout:
                logger.warning(f"⚠️ [STATE] Warmup timeout after {int(elapsed)}s! Entering READY fallback mode.")
                self.set_state(SystemState.READY)
                break
                
            await asyncio.sleep(5)

state_manager = StateManager()
