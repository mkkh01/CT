import asyncio
import logging
from enum import Enum

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
            cls._instance.data_threshold = 5 # Minimum klines/tickers before ready
        return cls._instance

    def set_state(self, new_state: SystemState):
        logger.info(f"🔄 [STATE] Transition: {self.state.value} -> {new_state.value}")
        self.state = new_state

    def is_ready(self):
        return self.state == SystemState.READY

    async def wait_for_ready(self):
        while not self.is_ready():
            await asyncio.sleep(1)

state_manager = StateManager()
