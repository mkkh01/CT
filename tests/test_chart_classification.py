from app.strategy import classify_candle, classify_chart, market_filter_diagnostics


def candle(open_price, high, low, close, index=0, volume=100.0):
    return {
        "open_time": index,
        "open": open_price,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
        "closed": True,
    }


def trend_candles(start=100.0, steps=120, direction=1, step=0.8, wick=0.05):
    candles = []
    close = start
    for index in range(steps):
        open_price = close
        close = close + direction * step
        candles.append(candle(open_price, max(open_price, close) + wick, min(open_price, close) - wick, close, index))
    return candles


def sideways_candles(start=100.0, steps=120):
    candles = []
    close = start
    pattern = (0.08, -0.08, 0.05, -0.05)
    for index in range(steps):
        open_price = close
        close = start + pattern[index % len(pattern)]
        candles.append(candle(open_price, max(open_price, close) + 0.03, min(open_price, close) - 0.03, close, index, volume=100.0))
    return candles


def test_candle_classifier_identifies_body_and_wick_patterns():
    previous = candle(105, 106, 99, 100, 0)
    bullish_engulfing = candle(99, 108, 98, 107, 1)
    hammer = candle(100, 103, 95, 102, 2)
    doji = candle(100, 105, 95, 100.2, 3)

    assert classify_candle(bullish_engulfing, previous)["pattern"] == "BULLISH_ENGULFING"
    assert classify_candle(hammer)["pattern"] == "HAMMER"
    assert classify_candle(doji)["pattern"] == "DOJI"


def test_chart_classifier_marks_strong_uptrend():
    execution = trend_candles(direction=1)
    higher = trend_candles(start=100.0, direction=1, step=1.6)
    result = classify_chart(execution, higher)

    assert result["chart_regime"] == "UPTREND"
    assert result["chart_regime_1h"] == "UPTREND"
    assert result["chart_regime_4h"] == "UPTREND"
    assert result["filter_passed"] is True
    assert result["adx"] is not None and result["adx"] >= 25.0
    assert result["plus_di"] > result["minus_di"]


def test_chart_classifier_rejects_sideways_market():
    execution = sideways_candles()
    higher = sideways_candles(start=110.0)
    result = classify_chart(execution, higher)

    assert result["chart_regime"] == "SIDEWAYS"
    assert result["filter_passed"] is False
    assert result["rejection_reason"] in {"SIDEWAYS_ADX_LOW", "SIDEWAYS_ATR_LOW", "EMA_ALIGNMENT_SIDEWAYS"}


def test_chart_classifier_rejects_downtrend_direction():
    execution = trend_candles(direction=-1)
    higher = trend_candles(start=180.0, direction=-1, step=1.6)
    result = market_filter_diagnostics(execution)

    assert result["market_regime"] == "DOWNTREND"
    assert result["filter_passed"] is False
    assert result["rejection_reason"] == "BEARISH_DIRECTIONAL_MOVEMENT"
    assert result["minus_di"] > result["plus_di"]


def test_signal_diagnostics_contains_both_timeframes_and_candle_gate():
    from app.strategy import evaluate_signal_diagnostics

    execution = trend_candles(direction=1)
    higher = trend_candles(start=100.0, direction=1, step=1.6)
    signal, diagnostics = evaluate_signal_diagnostics("BTCUSDT", execution, higher)

    assert signal is None
    assert diagnostics["candle_1h"]["pattern"] in {"BULLISH", "BULLISH_MARUBOZU"}
    assert diagnostics["candle_4h"]["direction"] == "BULLISH"
    assert "candle_pattern_confirmation" in diagnostics["conditions"]
