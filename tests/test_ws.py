import json

from app.binance_ws import BinanceMarketData
from app.config import Settings


def test_binance_combined_stream_message_is_parsed():
    prices = []
    candles = []
    settings = Settings(selected_symbols=["BTCUSDT"])
    client = BinanceMarketData(settings, lambda symbol, price: prices.append((symbol, price)), lambda symbol, interval, candle: candles.append((symbol, interval, candle)))
    message = {
        "stream": "btcusdt@kline_1h",
        "data": {
            "e": "kline",
            "s": "BTCUSDT",
            "k": {"t": 1, "T": 2, "i": "1h", "o": "100", "h": "105", "l": "99", "c": "104", "v": "10", "x": True},
        },
    }
    client._handle_message(json.dumps(message))
    assert candles[0][0:2] == ("BTCUSDT", "1h")
    assert candles[0][2]["close"] == 104.0

    ticker = {"stream": "btcusdt@miniTicker", "data": {"e": "24hrMiniTicker", "s": "BTCUSDT", "c": "104.5"}}
    client._handle_message(json.dumps(ticker))
    assert prices == [("BTCUSDT", 104.5)]


def test_stream_endpoints_include_market_data_primary_and_fallbacks():
    client = BinanceMarketData(Settings(selected_symbols=["BTCUSDT"]), lambda *_: None, lambda *_: None)
    endpoints = client._build_stream_urls()
    assert endpoints[0] == "wss://data-stream.binance.vision:443/stream"
    assert "wss://stream.binance.com:443/stream" in endpoints
    assert "wss://stream.binance.com:9443/stream" in endpoints


def test_stream_url_contains_all_dynamic_user_symbols():
    client = BinanceMarketData(Settings(selected_symbols=["BTCUSDT", "XRPUSDT"]), lambda *_: None, lambda *_: None)
    url = client._build_url()
    assert "btcusdt@kline_1h" in url
    assert "xrpusdt@kline_4h" in url
    assert "xrpusdt@miniTicker" in url


def test_data_readiness_is_separate_from_live_strategy_readiness():
    from collections import deque

    client = BinanceMarketData(Settings(selected_symbols=["BTCUSDT"]), lambda *_: None, lambda *_: None)
    candles = [{"open_time": index, "close_time": index + 1, "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.5, "volume": 10.0, "closed": True} for index in range(55)]
    client._candles[("BTCUSDT", "1h")] = deque(candles, maxlen=300)
    client._candles[("BTCUSDT", "4h")] = deque(candles, maxlen=300)

    disconnected = client.status_snapshot()
    assert disconnected["data_ready_symbols"] == ["BTCUSDT"]
    assert disconnected["strategy_ready_symbols"] == []
    assert disconnected["symbols"]["BTCUSDT"]["readiness_reason"] == "waiting_for_live_websocket"

    client._connected = True
    import time
    client._last_message_at = time.time()
    connected = client.status_snapshot()
    assert connected["strategy_ready_symbols"] == ["BTCUSDT"]


def test_connected_property_expires_stale_market_data():
    import time

    client = BinanceMarketData(Settings(selected_symbols=["BTCUSDT"], stale_data_seconds=60), lambda *_: None, lambda *_: None)
    client._connected = True
    client._last_message_at = time.time() - 61
    assert client.connected is False
