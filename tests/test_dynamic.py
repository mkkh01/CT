from app.config import Settings
from app.runtime import BotRuntime


def test_user_added_symbol_controls_prices_and_keyboard():
    runtime = BotRuntime(Settings(selected_symbols=[]))
    assert runtime.trader.selected_symbols == set()
    assert "BTCUSDT" not in runtime.prices_text()

    message = runtime.manage_coin("add:XRPUSDT:50")
    assert "XRPUSDT" in message
    assert runtime.trader.selected_symbols == {"XRPUSDT"}
    assert runtime.trader.capital_by_symbol["XRPUSDT"] == 50.0
    assert "XRPUSDT" in runtime.prices_text()
    keyboard_text = str(runtime.telegram_keyboard())
    assert "🔎 XRPUSDT" in keyboard_text
    assert "BTCUSDT" not in keyboard_text

    runtime.manage_coin("remove:XRPUSDT")
    assert runtime.trader.selected_symbols == set()
    assert "XRPUSDT" not in str(runtime.telegram_keyboard())


def test_dynamic_capital_update_keeps_symbol_selected():
    runtime = BotRuntime(Settings(selected_symbols=[]))
    runtime.manage_coin("add:SOLUSDT:25")
    runtime.manage_coin("update:SOLUSDT:40")
    assert runtime.trader.selected_symbols == {"SOLUSDT"}
    assert runtime.trader.capital_by_symbol["SOLUSDT"] == 40.0
