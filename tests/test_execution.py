import pytest

from app.config import Settings
from app.execution import BinanceSignedAdapter, ExecutionError, OrderIntent, PaperExecutionAdapter, build_execution_adapter


def test_paper_adapter_never_needs_credentials():
    settings = Settings(execution_mode="paper")
    adapter = build_execution_adapter(settings)
    assert isinstance(adapter, PaperExecutionAdapter)
    result = adapter.place_order(OrderIntent(client_order_id="paper-1", symbol="BTCUSDT", side="BUY", quantity="0.01"))
    assert result["status"] == "FILLED"
    assert result["mode"] == "paper"


def test_live_gate_rejects_missing_credentials():
    settings = Settings(execution_mode="live", live_trading_enabled=True, live_trading_confirmation="I_UNDERSTAND_LIVE_TRADING_RISK")
    adapter = BinanceSignedAdapter(settings)
    with pytest.raises(ExecutionError, match="missing_binance_execution_credentials"):
        adapter.place_order(OrderIntent(client_order_id="live-1", symbol="BTCUSDT", side="BUY", quantity="0.01"))


def test_live_gate_requires_explicit_confirmation():
    settings = Settings(execution_mode="live", binance_api_key="key", binance_api_secret="secret", live_trading_enabled=True)
    ready, reason = settings.live_execution_ready()
    assert ready is False
    assert reason == "live_confirmation_missing"
