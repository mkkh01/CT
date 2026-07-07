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
                    await asyncio.sleep(remaining_ban)
                    now = time.time()
                self.is_banned = False
                print(f"✨ [RATE LIMITER] انتهى الحظر. بدء فترة هدوء (5s)...")
                await asyncio.sleep(5)
                now = time.time()

            now = time.time()
            self.calls = [c for c in self.calls if now - c < self.period]
            
            while len(self.calls) + weight > self.max_calls:
                wait_time = self.period - (now - self.calls[0])
                if wait_time > 0:
                    await asyncio.sleep(wait_time)
                now = time.time()
                self.calls = [c for c in self.calls if now - c < self.period]

            for _ in range(weight):
                self.calls.append(now)

    def set_ban(self, duration):
        self.is_banned = True
        self.ban_until = time.time() + duration
        print(f"🛑 [RATE LIMITER] تم تفعيل الحظر لـ {duration} ثانية.")

rate_limiter = RateLimiter(max_calls=1000)

class DiagnosticLogger:
    @staticmethod
    def section(title):
        print(f"\n{'='*20} {title} {'='*20}")

    @staticmethod
    def system(msg, **kwargs):
        extra = f" | {' | '.join([f'{k}: {v}' for k, v in kwargs.items()])}" if kwargs else ""
        print(f"🖥️ [SYSTEM] {msg}{extra}")

    @staticmethod
    def data(symbol, timeframe, count, source, last_candle, from_cache, exec_time):
        cache_status = "CACHE ✅" if from_cache else "REST 🌐"
        print(f"📊 [DATA] {symbol} | {timeframe} | {count} Candles | {cache_status} | Source: {source} | Last: {last_candle} | Time: {exec_time:.3f}s")

    @staticmethod
    def regime(regime_data):
        DiagnosticLogger.section("MARKET REGIME")
        for k, v in regime_data.items():
            print(f"📈 {k:15}: {v}")
        print(f"📝 Reason: {regime_data.get('reason', 'N/A')}")

    @staticmethod
    def htf(htf_data):
        DiagnosticLogger.section("HTF ANALYSIS (1H)")
        for k, v in htf_data.items():
            if k != 'supported':
                print(f"🔭 {k:15}: {v}")
        status = "✅ SUPPORTED" if htf_data.get('supported') else "❌ REJECTED"
        print(f"🏁 HTF Status: {status} | Reason: {htf_data.get('reason', 'N/A')}")

    @staticmethod
    def indicators(ind_data):
        DiagnosticLogger.section("INDICATORS")
        for k, v in ind_data.items():
            print(f"🧪 {k:15}: {v}")

    @staticmethod
    def smt(smt_data):
        DiagnosticLogger.section("SMART MONEY (SMC)")
        for k, v in smt_data.items():
            print(f"💎 {k:15}: {v}")

    @staticmethod
    def scoring(score_data):
        DiagnosticLogger.section("FINAL SCORING")
        print(f"🎯 Total Score: {score_data.get('total', 0)}/100")
        print(f"🛡️ Quality: {score_data.get('quality', 0)}/100")
        print(f"📋 Verdict: {score_data.get('verdict', 'N/A')}")
        if score_data.get('reason'):
            print(f"💬 Reason: {score_data.get('reason')}")

diag_logger = DiagnosticLogger()

def log_api_request(symbol, timeframe, source, from_cache=False, execution_time=0, **kwargs):
    # الحفاظ على الوظيفة القديمة للتوافق ولكن استخدام DiagLogger داخلياً إذا أردنا
    status = "CACHE HIT" if from_cache else "CACHE MISS (REST)"
    now = datetime.now().strftime('%H:%M:%S')
    print(f"📝 [{now}] {status} | {symbol} | {timeframe} | {source} | {execution_time:.3f}s")
