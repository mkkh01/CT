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
