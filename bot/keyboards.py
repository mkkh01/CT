from telegram import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton

def get_main_menu():
    """لوحة التحكم الرئيسية (القائمة السفلية الثابتة)"""
    keyboard = [
        [KeyboardButton("🌟 الصفقات الخاصة")],
        [KeyboardButton("📈 الأسعار الحية")],
        [KeyboardButton("🧠 تقرير التدريب والتعلم")], 
        [KeyboardButton("💰 إدارة رأس المال")],
        [KeyboardButton("🌐 إدارة العملات")]
    ]
    bottom_row = [
        KeyboardButton("▶️ بدء التعلم الخفي"), 
        KeyboardButton("⏸️ إيقاف التعلم الخفي")
    ]
    return ReplyKeyboardMarkup(
        keyboard + [bottom_row], 
        resize_keyboard=True,
        one_time_keyboard=False
    )

def get_private_trades_menu():
    """قائمة التحكم في الإشارات والصفقات الخاصة"""
    keyboard = [
        [
            InlineKeyboardButton("🟢 تشغيل الإشارات", callback_data='elite_on'),
            InlineKeyboardButton("🔴 إيقاف الإشارات", callback_data='elite_off")
        ],
        [InlineKeyboardButton("📋 تقرير الأداء اللحظي", callback_data='elite_instant_report')],
        [InlineKeyboardButton("🔙 رجوع للرئيسية", callback_data='main_menu')]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_coins_menu():
    """قائمة إدارة العملات (تظهر بعد الضغط على إدارة العملات)"""
    keyboard = [
        [InlineKeyboardButton("➕ إضافة عملة جديدة", callback_data='add_coin')],
        [InlineKeyboardButton("➖ حذف عملة", callback_data='remove_coin')],
        [InlineKeyboardButton("📋 عرض الإعدادات", callback_data='view_coins')],
        [InlineKeyboardButton("🔙 رجوع للرئيسية", callback_data='main_menu')]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_timeframe_menu():
    """قائمة اختيار الإطار الزمني (تظهر أثناء إضافة عملة)"""
    keyboard = [
        [
            InlineKeyboardButton("1m", callback_data='tf_1m'),
            InlineKeyboardButton("5m", callback_data='tf_5m'),
            InlineKeyboardButton("15m", callback_data='tf_15m')
        ],
        [
            InlineKeyboardButton("1h", callback_data='tf_1h'),
            InlineKeyboardButton("4h", callback_data='tf_4h'),
            InlineKeyboardButton("1d", callback_data='tf_1d')
        ],
        [InlineKeyboardButton("🔙 رجوع", callback_data='coins')]
    ]
    return InlineKeyboardMarkup(keyboard)
