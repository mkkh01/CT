from app.config import Settings
from app.telegram_bot import TelegramBot


def test_add_coin_flow_requests_symbol_then_capital():
    managed = []
    messages = []
    bot = TelegramBot(
        Settings(telegram_chat_id="123", telegram_bot_token="token"),
        get_status=lambda: "status",
        get_prices=lambda: "prices",
        get_performance=lambda: "performance",
        get_positions=lambda: "positions",
        get_coins=lambda: "coins",
        manage_coin=lambda command: managed.append(command) or "saved",
        get_keyboard=lambda: {"keyboard": []},
        get_symbol_status=lambda symbol: symbol,
    )
    bot.send_message = lambda text, chat_id=None, with_keyboard=False: messages.append(text)

    bot._handle_text("123", "➕ إضافة عملة")
    assert bot._awaiting["123"] == "symbol"
    bot._handle_text("123", "SCUSDT")
    assert bot._awaiting["123"] == "capital"
    assert bot._pending_symbol["123"] == "SCUSDT"
    bot._handle_text("123", "30")

    assert managed == ["add:SCUSDT:30.0"]
    assert "123" not in bot._awaiting
    assert "123" not in bot._pending_symbol
