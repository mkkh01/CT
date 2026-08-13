from datetime import datetime, timezone

from app.config import Settings
from app.models import Signal
from app.strategy import ema, evaluate_signal
from app.virtual_trading import VirtualTradingEngine


def make_signal(symbol: str, price: float = 100.0) -> Signal:
    return Signal(
        symbol=symbol,
        timeframe="1h",
        generated_at=datetime.now(timezone.utc),
        candle_open_time=1,
        entry_price=price,
        stop_loss=price * 0.985,
        take_profit=price * 1.03,
        reason="test",
        risk_reward=2.0,
    )


def test_ema_requires_period_and_returns_value():
    assert ema([1.0, 2.0], 3) is None
    assert ema([1.0, 2.0, 3.0], 3) == 2.0


def test_virtual_engine_allows_at_most_five_positions():
    settings = Settings(selected_symbols=["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "ADAUSDT"])
    engine = VirtualTradingEngine(settings)
    for symbol in settings.selected_symbols:
        engine.set_capital(symbol, 50.0)

    opened = []
    for symbol in settings.selected_symbols:
        position, reason = engine.open_from_signal(make_signal(symbol))
        if position:
            opened.append(position)
    assert len(opened) == 5
    assert len(engine.positions) == 5
    assert engine.open_from_signal(make_signal("DOGEUSDT"))[1] == "symbol_not_selected"


def test_stop_loss_closes_virtual_position_and_records_pnl():
    settings = Settings(selected_symbols=["BTCUSDT"])
    engine = VirtualTradingEngine(settings)
    engine.set_capital("BTCUSDT", 50.0)
    position, reason = engine.open_from_signal(make_signal("BTCUSDT"))
    assert reason == "opened"
    assert position is not None

    closed = engine.on_price("BTCUSDT", position.stop_loss - 0.01)
    assert len(closed) == 1
    assert closed[0].status == "CLOSED"
    assert closed[0].close_reason == "STOP_LOSS"
    assert closed[0].realized_pnl < 0
    assert not engine.positions


def test_strategy_does_not_signal_with_insufficient_history():
    assert evaluate_signal("BTCUSDT", [], []) is None
