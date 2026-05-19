# bot/keyboards.py
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

def get_main_menu():
    """لوحة التحكم الرئيسية"""
    keyboard = [
        [InlineKeyboardButton("📊 التقرير الخفي للتعلم", callback_data='report')],
        [InlineKeyboardButton("💰 إدارة رأس المال", callback_data='capital')],
        [InlineKeyboardButton("🪙 إدارة العملات", callback_data='coins')],
        [
            InlineKeyboardButton("▶️ تشغيل", callback_data='start_sys'),
            InlineKeyboardButton("⏸️ إيقاف", callback_data='stop_sys')
        ]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_coins_menu():
    """قائمة العملات"""
    keyboard = [
        [InlineKeyboardButton("➕ إضافة عملة", callback_data='add_coin')],
        [InlineKeyboardButton("➖ حذف عملة", callback_data='remove_coin')],
        [InlineKeyboardButton("📋 عرض المراقبة", callback_data='view_coins')],
        [InlineKeyboardButton("🔙 رجوع", callback_data='main_menu')]
    ]
    return InlineKeyboardMarkup(keyboard)
