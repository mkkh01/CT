from __future__ import annotations

import pytest

from app.config import Settings
from app.market import BinanceMarketData, CandleStore
from app.models import Candle


def test_binance_websocket_kline_normalization():
    payload = {"data": {"k": {"s": "BTCUSDT", "i": "15m", "t": 1000, "T": 2000, "o": "100", "h": "105", "l": "99", "c": "104", "v": "250", "x": True}}}
    candle = BinanceMarketData._from_ws(payload)
    assert candle is not None
    assert candle.symbol == "BTCUSDT"
    assert candle.close == 104.0
    assert candle.is_closed is True


@pytest.mark.asyncio
async def test_candle_store_deduplicates_and_bounds_history():
    store = CandleStore(limit=2)
    for index in range(3):
        await store.upsert(Candle("BTCUSDT", "15m", index, index + 1, 10 + index, 12 + index, 9 + index, 11 + index, 1))
    await store.upsert(Candle("BTCUSDT", "15m", 2, 3, 20, 21, 19, 20.5, 2))
    snapshot = await store.snapshot("BTCUSDT", "15m")
    assert len(snapshot) == 2
    assert snapshot[-1].open_time == 2
    assert snapshot[-1].close == 20.5


def test_market_keeps_one_open_candle_beyond_closed_history_limit():
    settings = Settings(history_limit=500)
    market = BinanceMarketData(settings)
    assert market.store.limit == 501

    market = None
    settings = None


@pytest.mark.asyncio
async def test_closed_history_can_reach_configured_limit_with_open_candle():
    store = CandleStore(limit=501)
    for index in range(501):
        await store.upsert(Candle("BTCUSDT", "15m", index, index + 1, 10 + index, 12 + index, 9 + index, 11 + index, 1, index < 500))
    snapshot = await store.snapshot("BTCUSDT", "15m")
    assert len(snapshot) == 501
    assert sum(item.is_closed for item in snapshot) == 500
    assert snapshot[-1].is_closed is False
