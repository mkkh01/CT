from __future__ import annotations

from fastapi.testclient import TestClient

from app.analysis import AnalysisEngine
from app.config import SUPPORTED_TIMEFRAMES, Settings
from app.indicators import atr, detect_swings, ema, rsi
from app.main import create_app
from app.models import Candle


def make_candles(count: int = 80) -> list[Candle]:
    candles = []
    price = 100.0
    for index in range(count):
        drift = 0.35 if index % 7 != 0 else -0.15
        open_price = price
        close = price + drift
        high = max(open_price, close) + 0.4
        low = min(open_price, close) - 0.4
        candles.append(Candle("BTCUSDT", "15m", index * 900000, index * 900000 + 899999, open_price, high, low, close, 1000 + index, True))
        price = close
    return candles


def test_candle_validation_rejects_invalid_ohlc():
    bad = Candle("BTCUSDT", "15m", 0, 1, 10, 9, 8, 10, 1)
    try:
        bad.validate()
    except ValueError as exc:
        assert str(exc) == "high_below_open_or_close"
    else:
        raise AssertionError("invalid candle accepted")


def test_default_settings_support_requested_analysis_frames():
    settings = Settings()
    assert all(item in settings.analysis_timeframes for item in ("5m", "15m", "1h"))
    assert all(item in SUPPORTED_TIMEFRAMES for item in settings.stream_timeframes)
    assert settings.mtf_mapping["5m"] == ["15m", "1h"]
    assert settings.mtf_mapping["1h"] == ["4h", "1d"]


def test_indicators_are_deterministic():
    candles = make_candles()
    assert atr(candles, 14) > 0
    assert ema([1, 2, 3, 4], 3) == ema([1, 2, 3, 4], 3)
    assert 0 <= rsi(candles) <= 100
    assert detect_swings(candles, 3, 3) == detect_swings(candles, 3, 3)


def test_signal_plan_preserves_buy_rr_geometry():
    candles = make_candles()
    settings = Settings(min_signal_score=0, min_direction_gap=0, require_closed_candle=True)
    snapshot, result = AnalysisEngine(settings).analyze("BTCUSDT", "15m", candles, candles, candles, data_fresh=True)
    assert snapshot.symbol == "BTCUSDT"
    if getattr(result, "decision", None) == "BUY":
        assert result.stop_loss < result.entry < result.tp1 < result.tp2
        assert result.risk_reward["tp1"] == 1.0
        assert result.risk_reward["tp2"] == 2.0


def test_api_contracts_work_without_external_integrations():
    settings = Settings(symbols=["BTCUSDT"], disable_auto_start=True)
    with TestClient(create_app(settings)) as client:
        symbols = client.get("/api/v1/symbols")
        timeframes = client.get("/api/v1/timeframes")
        health = client.get("/healthz")
        assert symbols.status_code == 200
        assert symbols.json()["symbols"] == ["BTCUSDT"]
        assert timeframes.status_code == 200
        assert health.status_code == 200
        assert health.json()["started"] is True
        with client.websocket_connect("/ws/market") as websocket:
            first = websocket.receive_json()
            assert first["type"] == "status"
            assert first["channel"] == "market"
