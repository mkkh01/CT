import pandas as pd
import pytest

from run_backtest import BASE_COSTS, max_drawdown, validate_ohlcv


def test_costs_are_adverse_on_both_sides():
    assert BASE_COSTS.buy_multiplier > 1.0
    assert BASE_COSTS.sell_multiplier < 1.0
    assert BASE_COSTS.buy_multiplier * BASE_COSTS.sell_multiplier < 1.0


def test_validate_ohlcv_rejects_invalid_high_low_relationship():
    index = pd.date_range("2025-01-01", periods=2, freq="h", tz="UTC")
    bad = pd.DataFrame(
        {"open": [100.0, 100.0], "high": [99.0, 102.0], "low": [98.0, 99.0], "close": [100.0, 101.0], "volume": [1.0, 1.0]},
        index=index,
    )
    with pytest.raises(ValueError, match="invalid high/low"):
        validate_ohlcv(bad, "TESTUSDT")


def test_max_drawdown_uses_running_peak():
    equity = pd.Series([100.0, 120.0, 90.0, 110.0, 80.0])
    assert max_drawdown(equity) == pytest.approx(-1.0 / 3.0)
