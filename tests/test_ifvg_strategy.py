from app.ifvg_strategy import detect_fvgs, detect_ifvgs, evaluate_ifvg_signal_diagnostics


def candle(t, o, h, l, c, v=1000):
    return {"open_time": t, "open": o, "high": h, "low": l, "close": c, "volume": v}


def test_detect_bullish_and_bearish_fvg_geometry():
    bullish = [candle(1, 100, 101, 99, 100), candle(2, 100, 105, 100, 104), candle(3, 104, 108, 103, 107)]
    bearish = [candle(1, 107, 108, 104, 106), candle(2, 106, 106, 100, 101), candle(3, 101, 102, 98, 99)]
    assert detect_fvgs(bullish)[0]["direction"] == "BULLISH"
    assert detect_fvgs(bearish)[0]["direction"] == "BEARISH"


def test_ifvg_requires_close_beyond_zone_and_records_retest():
    candles = [
        candle(1, 100, 101, 99, 100),
        candle(2, 100, 105, 100, 104),
        candle(3, 104, 108, 103, 107),
        candle(4, 107, 106, 98, 99),
        candle(5, 99, 103, 97, 102),
        candle(6, 102, 104, 100, 103),
    ]
    zones = detect_ifvgs(candles)
    assert zones
    assert zones[0].ifvg_direction == "BEARISH"
    assert zones[0].inverted_at == 4


def test_insufficient_data_is_explicitly_not_ready():
    signal, diagnostics = evaluate_ifvg_signal_diagnostics("BTCUSDT", [candle(i, 100, 101, 99, 100) for i in range(10)], [candle(i, 100, 101, 99, 100) for i in range(10)])
    assert signal is None
    assert diagnostics["data_ready"] is False
    assert diagnostics["rejection_reason"] == "DATA_NOT_READY"
