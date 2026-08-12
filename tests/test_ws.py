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
