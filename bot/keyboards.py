from telegram import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton

def get_main_menu():
    """لوحة التحكم الرئيسية (ReplyKeyboardMarkup)"""
    keyboard = [
        [KeyboardButton("🌟 الصفقات الخاصة")],
        [KeyboardButton("📈 الأسعار الحية")],
        [KeyboardButton("🧠 تقرير التدريب والتعلم")], 
        [KeyboardButton("💰 إدارة رأس المال")],
        [KeyboardButton("🌐 إدارة العملات")]
    ]
    # أزرار التحكم في محرك التعلم أسفل الشاشة
    bottom_row = [
        KeyboardButton("▶️ بدء التعلم الخفي"), 
        KeyboardButton("⏸️ إيقاف التعلم الخفي")
    ]
    
    return ReplyKeyboardMarkup(keyboard + [bottom_row], resize_keyboard=True)

def get_private_trades_menu():
    """قائمة الصفقات الخاصة (Inline)"""
    keyboard = [
        [
            InlineKeyboardButton("🟢 تشغيل الإشارات", callback_data='elite_on'),
            InlineKeyboardButton("🔴 إيقاف الإشارات", callback_data='elite_off')
        ],
        [InlineKeyboardButton("📋 تقرير الأداء اللحظي", callback_data='elite_instant_report')],
        [InlineKeyboardButton("🔙 رجوع", callback_data='main_menu')]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_coins_menu():
    """إدارة العملات (Inline)"""
    keyboard = [
        [InlineKeyboardButton("➕ إضافة عملة جديدة", callback_data='add_coin')],
        [InlineKeyboardButton("➖ حذف عملة", callback_data='remove_coin')],
        [InlineKeyboardButton("📋 عرض الإعدادات", callback_data='view_coins')],
        [InlineKeyboardButton("🔙 رجوع", callback_data='main_menu')]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_timeframe_menu(symbol: str):
    """اختيار الإطار الزمني (الدالة التي طلبتها التقارير والمدخلات)"""
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
        ],
        [InlineKeyboardButton("🔙 رجوع", callback_data='coins')]
    ]
    return InlineKeyboardMarkup(keyboard)
