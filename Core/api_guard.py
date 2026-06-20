import asyncio
import time
import logging

logger = logging.getLogger(__name__)

class APIGuard:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(APIGuard, cls).__new__(cls)
            cls._instance.is_banned = False
            cls._instance.ban_until = 0
            cls._instance.current_weight = 0
            cls._instance.max_weight = 1200 # Binance default per minute
            cls._instance.lock = asyncio.Lock()
            cls._instance.backoff_time = 5
        return cls._instance

    async def check_wait(self, weight=1):
        """التحقق من الوزن الحالي والانتظار إذا لزم الأمر"""
        async with self.lock:
            if self.is_banned:
                wait_time = self.ban_until - time.time()
                if wait_time > 0:
                    logger.warning(f"🚫 [API GUARD] System is BANNED. Waiting for {wait_time:.2f}s")
                    await asyncio.sleep(wait_time)
                self.is_banned = False

            if self.current_weight + weight >= self.max_weight * 0.9:
                logger.warning("⚠️ [API GUARD] Approaching rate limit! Slowing down...")
                await asyncio.sleep(10)
                self.current_weight = 0

            self.current_weight += weight

    def report_error(self, status_code):
        """الإبلاغ عن أخطاء Binance وتطبيق الـ Backoff"""
        if status_code in [429, 418]:
            self.is_banned = True
            self.ban_until = time.time() + self.backoff_time
            logger.error(f"❌ [API GUARD] BANNED! Code: {status_code}. Wait: {self.backoff_time}s")
            self.backoff_time = min(self.backoff_time * 2, 3600) # Exponential backoff up to 1 hour
        else:
            # تقليل مدة الـ backoff تدريجياً عند النجاح (يتم استدعاؤها في مكان آخر)
            self.backoff_time = max(5, self.backoff_time - 1)

    def update_weight(self, weight_header):
        """تحديث الوزن بناءً على استجابة Binance (X-MBX-USED-WEIGHT)"""
        try:
            self.current_weight = int(weight_header)
        except Exception as e:
            logger.debug(f"Could not parse weight header: {e}")

api_guard = APIGuard()
