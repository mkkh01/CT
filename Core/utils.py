import asyncio
import time
import logging
from datetime import datetime

# إعداد الـ Logger المركزي
logger = logging.getLogger("CT_System")
logger.setLevel(logging.INFO)

class RateLimiter:
    def __init__(self, max_calls=1200, period=60):
        self.max_calls = max_calls
        self.period = period
        self.calls = []
        self.lock = asyncio.Lock()
        self.is_banned = False
        self.ban_until = 0

    async def wait_if_needed(self, weight=1):
        async with self.lock:
            now = time.time()
            if self.is_banned:
                remaining_ban = self.ban_until - now
                if remaining_ban > 0:
                    # لا نطبع الرسالة في كل مرة لتقليل الضجيج، فقط عند الضرورة
                    await asyncio.sleep(remaining_ban)
                    now = time.time()
                self.is_banned = False
                # فترة هدوء إضافية بعد الحظر لضمان استقرار API
                print(f"✨ [RATE LIMITER] انتهى الحظر. بدء فترة هدوء (5s)...")
                await asyncio.sleep(5)
                now = time.time()

            now = time.time()
            self.calls = [c for c in self.calls if now - c < self.period]
            
            while len(self.calls) + weight > self.max_calls:
                wait_time = self.period - (now - self.calls[0])
                if wait_time > 0:
                    # print(f"⏳ [RATE LIMITER] تم الوصول للحد الأقصى. الانتظار لـ {wait_time:.1f} ثانية...")
                    await asyncio.sleep(wait_time)
                now = time.time()
                self.calls = [c for c in self.calls if now - c < self.period]

            for _ in range(weight):
                self.calls.append(now)

    def set_ban(self, duration):
        self.is_banned = True
        self.ban_until = time.time() + duration
        print(f"🛑 [RATE LIMITER] تم تفعيل الحظر لـ {duration} ثانية.")

rate_limiter = RateLimiter(max_calls=1000) # نترك هامش أمان (Binance limit is 1200/min)

def log_api_request(symbol, timeframe, source, from_cache=False, execution_time=0, **kwargs):
    status = "CACHE HIT" if from_cache else "CACHE MISS (REST)"
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    extra = f" | Extra: {kwargs}" if kwargs else ""
    print(f"📝 [{now}] {status} | {symbol} | {timeframe} | Source: {source} | Time: {execution_time:.3f}s{extra}")
