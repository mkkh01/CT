from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .backtest import run_backtest
from .config import SUPPORTED_TIMEFRAMES, Settings
from .service import IndicatorService

BASE_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = BASE_DIR / "static"


def create_app(settings: Settings | None = None) -> FastAPI:
    app_settings = settings or Settings.from_env()
    logging.basicConfig(level=getattr(logging, app_settings.log_level, logging.INFO), format="%(asctime)s %(levelname)s %(name)s %(message)s")
    service = IndicatorService(app_settings)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        await service.start()
        yield
        await service.stop()

    app = FastAPI(title=app_settings.app_name, version=app_settings.app_version, lifespan=lifespan)
    app.state.settings = app_settings
    app.state.service = service
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=False, allow_methods=["GET", "POST"], allow_headers=["*"])
    if STATIC_DIR.exists():
        app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    @app.get("/", include_in_schema=False)
    async def root():
        index = STATIC_DIR / "index.html"
        return FileResponse(index) if index.exists() else JSONResponse({"name": app_settings.app_name, "status": "ok"})

    @app.get("/healthz")
    async def healthz():
        status = service.status()
        return {"status": "ok", "service": app_settings.app_name, "integrations": status["integrations"], "market_connected": status["market"]["connected"], "started": status["started"]}

    @app.get("/api/v1/health")
    async def api_health():
        return service.status()

    @app.get("/api/v1/symbols")
    async def symbols():
        return {"symbols": app_settings.symbols, "count": len(app_settings.symbols), "exchange": app_settings.exchange, "market_type": app_settings.market_type}

    @app.get("/api/v1/timeframes")
    async def timeframes():
        return {"timeframes": SUPPORTED_TIMEFRAMES, "entry": app_settings.entry_timeframe, "structure": app_settings.structure_timeframe, "htf": app_settings.htf_timeframe, "mapping": app_settings.mtf_mapping}

    @app.get("/api/v1/candles/{symbol}/{timeframe}")
    async def candles(symbol: str, timeframe: str, limit: int = Query(default=300, ge=1, le=1000)):
        if symbol.upper() not in app_settings.symbols:
            raise HTTPException(status_code=404, detail="unsupported_symbol")
        if timeframe.lower() not in SUPPORTED_TIMEFRAMES:
            raise HTTPException(status_code=400, detail="unsupported_timeframe")
        return {"symbol": symbol.upper(), "timeframe": timeframe.lower(), "candles": await service.get_candles(symbol, timeframe, limit)}

    @app.get("/api/v1/analysis/{symbol}")
    async def analysis_default(symbol: str):
        return await service.get_analysis(symbol, app_settings.entry_timeframe)

    @app.get("/api/v1/analysis/{symbol}/{timeframe}")
    async def analysis(symbol: str, timeframe: str):
        if symbol.upper() not in app_settings.symbols:
            raise HTTPException(status_code=404, detail="unsupported_symbol")
        return await service.get_analysis(symbol, timeframe)

    @app.get("/api/v1/signals/active")
    async def active_signals():
        return {"signals": [item.to_dict() for item in service._signals.values() if item.status in {"SIGNAL_CONFIRMED", "ENTRY_PENDING", "ACTIVE"}]}

    @app.get("/api/v1/signals/{symbol}/{timeframe}")
    async def signals(symbol: str, timeframe: str, limit: int = Query(default=50, ge=1, le=200)):
        return {"symbol": symbol.upper(), "timeframe": timeframe.lower(), "signals": await service.get_signals(symbol, timeframe, limit)}

    @app.post("/api/v1/backtests")
    async def backtests(symbol: str, timeframe: str, limit: int = Query(default=500, ge=100, le=1000)):
        if symbol.upper() not in app_settings.symbols:
            raise HTTPException(status_code=404, detail="unsupported_symbol")
        candles = await service.market.snapshot(symbol.upper(), timeframe.lower())
        return run_backtest(candles[-limit:], app_settings)

    @app.get("/api/v1/settings")
    async def settings():
        return {"app": {"name": app_settings.app_name, "version": app_settings.app_version, "timezone": app_settings.timezone}, "market": {"exchange": app_settings.exchange, "market_type": app_settings.market_type}, "signal": {"min_score": app_settings.min_signal_score, "min_direction_gap": app_settings.min_direction_gap, "require_closed_candle": app_settings.require_closed_candle}, "risk": {"tp1_rr": app_settings.rr_tp1, "tp2_rr": app_settings.rr_tp2}, "multi_timeframe": app_settings.mtf_mapping, "config_version": app_settings.config_version}

    async def websocket_status(websocket: WebSocket, channel: str):
        await websocket.accept()
        try:
            while True:
                await websocket.send_json({"channel": channel, "type": "status", "payload": service.status()})
                await asyncio.sleep(5)
        except (WebSocketDisconnect, asyncio.CancelledError):
            return

    @app.websocket("/ws/market")
    async def market_socket(websocket: WebSocket):
        await websocket_status(websocket, "market")

    @app.websocket("/ws/analysis")
    async def analysis_socket(websocket: WebSocket):
        await websocket_status(websocket, "analysis")

    @app.websocket("/ws/signals")
    async def signals_socket(websocket: WebSocket):
        await websocket_status(websocket, "signals")

    return app


app = create_app()
