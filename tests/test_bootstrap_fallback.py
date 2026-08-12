from app.binance_ws import BinanceMarketData
from app.config import Settings


class FakeResponse:
    status_code = 418
    headers = {}


def test_rest_rate_limit_uses_websocket_api_fallback(monkeypatch):
    market = BinanceMarketData(Settings(selected_symbols=["BTCUSDT"]), lambda *_: None, lambda *_: None)
    monkeypatch.setattr(market._rest_session, "get", lambda *args, **kwargs: FakeResponse())
    expected = [[1, "1", "1", "1", "1", "1", 2, "1", 1, "1", "1", "0"]]
    monkeypatch.setattr(market, "_fetch_klines_via_ws_api", lambda symbol, interval: expected)

    result = market._fetch_klines("BTCUSDT", "1h")

    assert result == expected
    assert market._bootstrap_rate_limited_until > 0
