import pytest
from app.strategy import detect_market_structure, bollinger_bands_squeeze

def test_market_structure_bullish():
    # Construct synthetic candles with higher highs and higher lows
    candles = []
    base_price = 100.0
    for i in range(20):
        base_price += 1.0
        candles.append({
            "open": base_price - 0.5,
            "high": base_price + 1.5,
            "low": base_price - 1.0,
            "close": base_price,
            "volume": 1000.0
        })
    structure = detect_market_structure(candles, lookback=5)
    assert structure == "BULLISH_STRUCTURE"

def test_bollinger_squeeze():
    candles = [{"open": 100, "high": 102, "low": 98, "close": 100, "volume": 1000} for _ in range(30)]
    bb = bollinger_bands_squeeze(candles, period=20)
    assert "squeeze" in bb
    assert "bandwidth" in bb
    assert bb["bandwidth"] >= 0.0
