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
