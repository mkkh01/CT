# bot/keyboards.py
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

def get_main_menu():
    keyboard = [
        [InlineKeyboardButton("📈 الأسعار الحية", callback_data='live_prices')],
        [InlineKeyboardButton("📊 التقرير الخفي للتعلم", callback_data='report')],
        [InlineKeyboardButton("💰 إدارة رأس المال الكلي", callback_data='capital')],
        [InlineKeyboardButton("🪙 إدارة العملات (متقدم)", callback_data='coins')],
        [
            InlineKeyboardButton("▶️ تشغيل", callback_data='start_sys'),
            InlineKeyboardButton("⏸️ إيقاف", callback_data='stop_sys')
        ]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_coins_menu():
    keyboard = [
        [InlineKeyboardButton("➕ إضافة عملة جديدة", callback_data='add_coin')],
        [InlineKeyboardButton("➖ حذف عملة", callback_data='remove_coin')],
        [InlineKeyboardButton("📋 عرض العملات وإعداداتها", callback_data='view_coins')],
        [InlineKeyboardButton("🔙 رجوع", callback_data='main_menu')]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_timeframe_menu(symbol: str):
    """أزرار اختيار الإطار الزمني للعملة"""
    keyboard = [
        [
            InlineKeyboardButton("1m", callback_data=f'tf_1m_{symbol}'),
            InlineKeyboardButton("5m", callback_data=f'tf_5m_{symbol}'),
            InlineKeyboardButton("15m", callback_data=f'tf_15m_{symbol}')
        ],
        [
            InlineKeyboardButton("1h", callback_data=f'tf_1h_{symbol}'),
            InlineKeyboardButton("4h", callback_data=f'tf_4h_{symbol}'),
            InlineKeyboardButton("1d", callback_data=f'tf_1d_{symbol}')
        ]
    ]
    return InlineKeyboardMarkup(keyboard)
