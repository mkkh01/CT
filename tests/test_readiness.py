from app.binance_ws import BinanceMarketData
from app.config import Settings
from app.runtime import BotRuntime


def test_market_readiness_requires_55_closed_candles_per_interval():
    market = BinanceMarketData(Settings(selected_symbols=["BTCUSDT"]), lambda *_: None, lambda *_: None)
    status = market.status_snapshot()
    pair = status["symbols"]["BTCUSDT"]
    assert pair["ready_for_strategy"] is False
    assert pair["required_closed_candles"] == 55
    assert pair["readiness_reason"] == "waiting_for_55_closed_candles_on_1h_and_4h"


def test_runtime_marks_strategy_data_not_ready_instead_of_no_signal():
    runtime = BotRuntime(Settings(selected_symbols=["BTCUSDT"]))
    runtime._on_closed_candle("BTCUSDT", "1h", {"open_time": 1, "close": 100.0})
    assert runtime.last_decision is not None
    assert runtime.last_decision["decision"] == "DATA_NOT_READY"
    assert runtime.last_decision["data_ready"] is False
