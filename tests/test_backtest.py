from __future__ import annotations

from app.backtest import run_backtest
from app.config import Settings
from app.models import Candle


def test_backtest_returns_required_metrics_for_fixed_history():
    candles = []
    price = 100.0
    for index in range(120):
        close = price + (0.25 if index % 5 else -0.1)
        candles.append(Candle("BTCUSDT", "15m", index * 900000, index * 900000 + 899999, price, max(price, close) + 0.3, min(price, close) - 0.3, close, 1000 + index, True))
        price = close
    result = run_backtest(candles, Settings(min_signal_score=0, min_direction_gap=0))
    assert result["status"] == "OK"
    assert result["tp2_hits"] == 0
    assert result["tp2_rate"] == 0.0
    for key in ("total_signals", "activated_trades", "tp1_hits", "tp2_hits", "sl_hits", "win_rate", "average_r", "total_r", "maximum_drawdown", "profit_factor"):
        assert key in result


def test_backtest_waits_for_entry_before_counting_exit(monkeypatch):
    import app.backtest as backtest_module
    from app.models import NoTrade, Signal

    candles = [Candle("BTCUSDT", "15m", index * 900000, index * 900000 + 899999, 100, 101, 99, 100, 1000, True) for index in range(56)]

    class FakeEngine:
        def __init__(self, settings):
            pass

        def analyze(self, symbol, timeframe, history, structure, htf, data_fresh=True):
            if len(history) != 51:
                return None, NoTrade(symbol, timeframe)
            signal = Signal(
                id="backtest-entry-gate", symbol=symbol, timeframe=timeframe, direction="BUY", status="SIGNAL_CONFIRMED", score=90,
                entry=100, stop_loss=95, tp1=105, tp2=110, created_at="2026-01-01T00:00:00+00:00", signal_version="test",
                risk_reward={"tp1": 1.0, "tp2": 2.0}, reasons=[], structure={}, liquidity={}, fvg={}, order_block={},
                volume={}, momentum={}, trend={}, data_health={}, metadata={"entry_open_time": history[-1].open_time},
            )
            return None, signal

    candles[51] = Candle("BTCUSDT", "15m", 51 * 900000, 51 * 900000 + 899999, 96, 96, 94, 95, 1000, True)
    candles[52] = Candle("BTCUSDT", "15m", 52 * 900000, 52 * 900000 + 899999, 99, 101, 99, 100, 1000, True)
    candles[53] = Candle("BTCUSDT", "15m", 53 * 900000, 53 * 900000 + 899999, 100, 106, 99, 105, 1000, True)
    monkeypatch.setattr(backtest_module, "AnalysisEngine", FakeEngine)

    result = backtest_module.run_backtest(candles, Settings(max_pending_candles=10))
    assert result["activated_trades"] == 1
    assert result["sl_hits"] == 0
    assert result["tp1_hits"] == 1
    assert result["trades"][0]["entry_time"] == 52 * 900000
