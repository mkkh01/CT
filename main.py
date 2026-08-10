import os, asyncio, logging, sys, signal
from fastapi import FastAPI
import uvicorn

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
log = logging.getLogger("main")

PORT = int(os.getenv("PORT", os.getenv("APP_PORT", 8000)))

app = FastAPI(title="CT Trading System v1.3")

from core.config import settings
from services.supabase_client import supabase
from services.redis_client import redis_client
from core.market_data import MarketData
from core.analysis import AnalysisEngine
from core.risk_manager import RiskManager
from core.signals import SignalGenerator

market = MarketData()
engine = AnalysisEngine()
risk = RiskManager()
signals = SignalGenerator()

# ✅ المسارات الصحيحة
@app.get("/health")
def health():
    return {"status": "ok", "system": settings.SYSTEM_ENABLED, "symbols": settings.SYMBOLS}

@app.get("/")
def root():
    return {
        "name": "CT Trading System v1.3",
        "status": "✅ ONLINE",
        "health_check": "/health",
        "symbols": settings.SYMBOLS
    }

async def main_loop():
    try:
        await asyncio.gather(
            market.start(),
            engine.start(market),
            risk.start(),
            signals.start(engine, risk),
        )
    except Exception as e:
        log.exception("Main loop error: %s", e)

async def start_bot_safe():
    """تشغيل البوت مع تجاهل تعارض التوكن"""
    try:
        from core.telegram_bot import TelegramBot
        tg = TelegramBot()
        await tg.start()
        return tg
    except Exception as e:
        if "Conflict" in str(e):
            log.warning("⚠️ Bot conflict: another instance running elsewhere — bot disabled on this deploy")
        else:
            log.error("⚠️ Telegram bot failed: %s", e)
        return None

@app.on_event("startup")
async def startup():
    log.info("✅ Supabase: %s", "connected" if supabase else "not configured")
    log.info("✅ Redis: %s", "connected" if redis_client and redis_client.ping() else "not connected")
    asyncio.create_task(main_loop())
    asyncio.create_task(start_bot_safe())
    log.info("🚀 SYSTEM FULLY ONLINE — 1D → 4H → 1H")

def _quit(*a):
    log.info("🛑 Shutting down...")
    sys.exit(0)

if __name__ == "__main__":
    signal.signal(signal.SIGINT, _quit)
    signal.signal(signal.SIGTERM, _quit)
    uvicorn.run(app, host="0.0.0.0", port=PORT, log_level="info")
