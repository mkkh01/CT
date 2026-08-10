import os, asyncio, logging
from fastapi import FastAPI
import uvicorn

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
log = logging.getLogger("main")

app = FastAPI(title="CT Trading System")

from core.config import settings
from services.supabase_client import supabase
from services.redis_client import redis_client
from core.market_data import MarketData
from core.analysis import AnalysisEngine
from core.risk_manager import RiskManager
from core.signals import SignalGenerator
from core.telegram_bot import TelegramBot

market = MarketData()
engine = AnalysisEngine()
risk = RiskManager()
signals = SignalGenerator()
tg = TelegramBot()

@app.get("/health")
async def health():
    return {"status":"ok","system":settings.SYSTEM_ENABLED,"symbols":settings.SYMBOLS}

async def main_loop():
    await asyncio.gather(
        market.start(),
        engine.start(market),
        risk.start(),
        signals.start(engine, risk, tg),
        tg.start(),
    )

@app.on_event("startup")
async def startup():
    log.info("✅ Supabase: %s", "connected" if supabase else "init")
    log.info("✅ Redis: %s", "connected" if redis_client.ping() else "fail")
    asyncio.create_task(main_loop())
    log.info("🚀 SYSTEM FULLY ONLINE — 1D → 4H → 1H")

if __name__ == "__main__":
    port = int(os.getenv("PORT", os.getenv("APP_PORT", 8000)))
    uvicorn.run(app, host="0.0.0.0", port=port)
