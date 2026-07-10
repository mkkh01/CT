from telegram import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from config.constants import *

def get_main_menu():
    keyboard = [
        [KeyboardButton(BUTTON_STATUS), KeyboardButton(BUTTON_TRADES)],
        [KeyboardButton(BUTTON_SETTINGS), KeyboardButton(BUTTON_CAPITAL)],
        [KeyboardButton(BUTTON_RISK), KeyboardButton(BUTTON_COINS)],
        [KeyboardButton(BUTTON_LOGS), KeyboardButton(BUTTON_PERFORMANCE)],
        [KeyboardButton(BUTTON_START), KeyboardButton(BUTTON_STOP)]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def get_settings_menu():
    keyboard = [
        [InlineKeyboardButton("📊 تحديث الإحصائيات", callback_data='refresh_stats')],
        [InlineKeyboardButton("🧠 تقرير الذكاء الاصطناعي", callback_data='ai_report')],
        [InlineKeyboardButton("🔙 رجوع", callback_data='main_menu')]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_risk_menu():
    keyboard = [
        [InlineKeyboardButton(f"{r*100}%", callback_data=f'set_risk_{r}') for r in RISK_LEVELS],
        [InlineKeyboardButton("🔙 رجوع", callback_data='main_menu')]
    ]
    return InlineKeyboardMarkup(keyboard)
