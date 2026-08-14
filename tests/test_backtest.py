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
