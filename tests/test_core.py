from __future__ import annotations

from fastapi.testclient import TestClient

from app.analysis import AnalysisEngine
from app.config import SUPPORTED_TIMEFRAMES, Settings
from app.indicators import atr, detect_swings, ema, rsi
from app.main import create_app
from app.models import Candle, Signal
from app.service import IndicatorService


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
    assert settings.history_limit == 500
    assert len(settings.symbols) == 40


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


def test_trades_endpoint_is_available_without_external_integrations():
    settings = Settings(symbols=["BTCUSDT"], disable_auto_start=True)
    with TestClient(create_app(settings)) as client:
        response = client.get("/api/v1/trades?symbol=BTCUSDT&timeframe=5m")
        assert response.status_code == 200
        assert response.json() == {"trades": [], "active_only": False}


def test_trade_lifecycle_records_entry_and_tp1_reason():
    async def scenario():
        service = IndicatorService(Settings(symbols=["BTCUSDT"], disable_auto_start=True))
        signal = Signal(
            id="trade-test-1", symbol="BTCUSDT", timeframe="5m", direction="BUY", status="SIGNAL_CONFIRMED",
            score=72, entry=100, stop_loss=95, tp1=105, tp2=110, created_at="2026-01-01T00:00:00+00:00",
            signal_version="test", risk_reward={"tp1": 1.0, "tp2": 2.0}, reasons=["test reason"],
            structure={}, liquidity={}, fvg={}, order_block={}, volume={}, momentum={}, trend={}, data_health={}, metadata={"entry_open_time": 0},
        )
        service._signals[signal.id] = signal
        await service._update_signal_lifecycle(Candle("BTCUSDT", "5m", 0, 299999, 99, 101, 98, 100, 10, True))
        assert service._trades[signal.id].status == "ACTIVE"
        await service._update_signal_lifecycle(Candle("BTCUSDT", "5m", 300000, 599999, 104, 106, 103, 105, 10, True))
        trade = service._trades[signal.id]
        assert trade.status == "TP1_HIT"
        assert trade.close_reason == "TP1_REACHED"
        assert trade.last_price == 105

    import asyncio
    asyncio.run(scenario())


def test_trade_views_split_current_and_completed():
    from app.models import Trade

    settings = Settings(symbols=["BTCUSDT"], disable_auto_start=True)
    app = create_app(settings)
    with TestClient(app) as client:
        service = app.state.service
        service._trades["active-1"] = Trade(
            id="active-1", signal_id="signal-active", symbol="BTCUSDT", timeframe="15m", direction="BUY",
            status="ACTIVE", score=85, entry=100, stop_loss=95, tp1=105, tp2=110, created_at="2026-01-01T00:00:00+00:00", last_price=102,
        )
        service._trades["closed-1"] = Trade(
            id="closed-1", signal_id="signal-closed", symbol="BTCUSDT", timeframe="15m", direction="SELL",
            status="SL_HIT", score=82, entry=100, stop_loss=105, tp1=95, tp2=90, created_at="2026-01-01T00:01:00+00:00",
            exit_at="2026-01-01T00:20:00+00:00", exit_price=105, close_reason="STOP_LOSS_REACHED",
        )
        current = client.get("/api/v1/trades/current", params={"symbol": "BTCUSDT", "timeframe": "15m"})
        completed = client.get("/api/v1/trades/completed", params={"symbol": "BTCUSDT", "timeframe": "15m"})
        assert current.status_code == 200
        assert completed.status_code == 200
        assert [row["id"] for row in current.json()["trades"]] == ["active-1"]
        assert [row["id"] for row in completed.json()["trades"]] == ["closed-1"]


def test_tp1_hit_is_not_an_active_signal():
    settings = Settings(symbols=["BTCUSDT"], disable_auto_start=True)
    app = create_app(settings)
    with TestClient(app) as client:
        service = app.state.service
        service._signals["tp1-signal"] = Signal(
            id="tp1-signal", symbol="BTCUSDT", timeframe="15m", direction="BUY", status="TP1_HIT", score=85,
            entry=100, stop_loss=95, tp1=105, tp2=110, created_at="2026-01-01T00:00:00+00:00", signal_version="test",
            risk_reward={"tp1": 1.0, "tp2": 2.0}, reasons=[], structure={}, liquidity={}, fvg={}, order_block={},
            volume={}, momentum={}, trend={}, data_health={}, metadata={},
        )
        response = client.get("/api/v1/signals/active")
        assert response.status_code == 200
        assert response.json()["signals"] == []


def test_summary_endpoints_group_active_signals_and_successful_trades_by_symbol():
    from app.models import Trade

    settings = Settings(symbols=["BTCUSDT", "ETHUSDT"], disable_auto_start=True)
    app = create_app(settings)
    with TestClient(app) as client:
        service = app.state.service
        for index, symbol in enumerate(("BTCUSDT", "ETHUSDT")):
            service._signals[f"active-{index}"] = Signal(
                id=f"active-{index}", symbol=symbol, timeframe="15m", direction="BUY", status="ACTIVE", score=85,
                entry=100, stop_loss=95, tp1=105, tp2=110, created_at=f"2026-01-01T00:0{index}:00+00:00", signal_version="test",
                risk_reward={"tp1": 1.0, "tp2": 2.0}, reasons=[], structure={}, liquidity={}, fvg={}, order_block={},
                volume={}, momentum={}, trend={}, data_health={}, metadata={},
            )
        service._trades["successful-btc"] = Trade(
            id="successful-btc", signal_id="successful-btc-signal", symbol="BTCUSDT", timeframe="15m", direction="BUY",
            status="TP1_HIT", score=90, entry=100, stop_loss=95, tp1=105, tp2=110, created_at="2026-01-01T00:02:00+00:00",
            exit_at="2026-01-01T01:00:00+00:00", exit_price=105, close_reason="TP1_REACHED",
        )
        active = client.get("/api/v1/signals/active/summary")
        successful = client.get("/api/v1/trades/successful/summary")
        assert active.json()["total"] == 2
        assert {item["symbol"] for item in active.json()["groups"]} == {"BTCUSDT", "ETHUSDT"}
        assert successful.json()["total"] == 1
        assert successful.json()["groups"][0]["symbol"] == "BTCUSDT"
        assert successful.json()["definition"] == "TP1_HIT"


def test_live_candle_closes_buy_and_sell_at_tp1():
    async def scenario():
        buy_service = IndicatorService(Settings(symbols=["BTCUSDT"], disable_auto_start=True))
        buy_signal = Signal(
            id="live-buy", symbol="BTCUSDT", timeframe="5m", direction="BUY", status="ACTIVE",
            score=80, entry=100, stop_loss=95, tp1=105, tp2=110, created_at="2026-01-01T00:00:00+00:00",
            signal_version="test", risk_reward={"tp1": 1.0, "tp2": 2.0}, reasons=[], structure={}, liquidity={},
            fvg={}, order_block={}, volume={}, momentum={}, trend={}, data_health={}, metadata={"entry_open_time": 0},
        )
        buy_service._signals[buy_signal.id] = buy_signal
        buy_service._trades[buy_signal.id] = buy_service._trade_from_signal(buy_signal)
        await buy_service.on_candle(Candle("BTCUSDT", "5m", 0, 299999, 100, 106, 99, 104, 10, False))
        assert buy_service._trades[buy_signal.id].status == "TP1_HIT"

        sell_service = IndicatorService(Settings(symbols=["BTCUSDT"], disable_auto_start=True))
        sell_signal = Signal(
            id="live-sell", symbol="BTCUSDT", timeframe="5m", direction="SELL", status="ACTIVE",
            score=80, entry=100, stop_loss=105, tp1=95, tp2=90, created_at="2026-01-01T00:00:00+00:00",
            signal_version="test", risk_reward={"tp1": 1.0, "tp2": 2.0}, reasons=[], structure={}, liquidity={},
            fvg={}, order_block={}, volume={}, momentum={}, trend={}, data_health={}, metadata={"entry_open_time": 0},
        )
        sell_service._signals[sell_signal.id] = sell_signal
        sell_service._trades[sell_signal.id] = sell_service._trade_from_signal(sell_signal)
        await sell_service.on_candle(Candle("BTCUSDT", "5m", 0, 299999, 100, 101, 94, 96, 10, False))
        assert sell_service._trades[sell_signal.id].status == "TP1_HIT"

    import asyncio
    asyncio.run(scenario())


def test_trade_lifecycle_activates_sell_at_entry():
    async def scenario():
        service = IndicatorService(Settings(symbols=["BTCUSDT"], disable_auto_start=True))
        signal = Signal(
            id="sell-entry-test", symbol="BTCUSDT", timeframe="5m", direction="SELL", status="SIGNAL_CONFIRMED",
            score=80, entry=100, stop_loss=105, tp1=95, tp2=90, created_at="2026-01-01T00:00:00+00:00",
            signal_version="test", risk_reward={"tp1": 1.0, "tp2": 2.0}, reasons=["test reason"], structure={},
            liquidity={}, fvg={}, order_block={}, volume={}, momentum={}, trend={}, data_health={}, metadata={"entry_open_time": 0},
        )
        service._signals[signal.id] = signal
        await service._update_signal_lifecycle(Candle("BTCUSDT", "5m", 0, 299999, 101, 102, 99, 101, 10, True))
        assert service._trades[signal.id].status == "ACTIVE"
        assert service._trades[signal.id].activated_at is not None

    import asyncio
    asyncio.run(scenario())


def test_completed_storage_state_replaces_stale_local_active_state():
    from app.models import Trade

    class FakeStorage:
        enabled = True

        async def list_trades(self, symbol=None, timeframe=None, limit=100, active_only=False):
            return [
                Trade(
                    id="stale-trade", signal_id="stale-signal", symbol="BTCUSDT", timeframe="15m", direction="BUY",
                    status="TP1_HIT", score=90, entry=100, stop_loss=95, tp1=105, tp2=110,
                    created_at="2026-01-01T00:00:00+00:00", exit_at="2026-01-01T01:00:00+00:00",
                    exit_price=105, close_reason="TP1_REACHED",
                ).to_dict()
            ]

    async def scenario():
        service = IndicatorService(Settings(symbols=["BTCUSDT"], disable_auto_start=True))
        service.storage = FakeStorage()
        service._trades["stale-trade"] = Trade(
            id="stale-trade", signal_id="stale-signal", symbol="BTCUSDT", timeframe="15m", direction="BUY",
            status="ACTIVE", score=90, entry=100, stop_loss=95, tp1=105, tp2=110,
            created_at="2026-01-01T00:00:00+00:00", last_price=105,
        )
        current = await service.get_trades(symbol="BTCUSDT", timeframe="15m", active_only=True)
        completed = await service.get_trades(symbol="BTCUSDT", timeframe="15m", completed_only=True)
        assert current == []
        assert [row["status"] for row in completed] == ["TP1_HIT"]

    import asyncio
    asyncio.run(scenario())
