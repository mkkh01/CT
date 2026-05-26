from telegram import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton

def get_main_menu():
    """لوحة التحكم الرئيسية (الأزرار الكبيرة أسفل الشاشة)"""
    # الأزرار الرئيسية كما طلبت
    keyboard = [
        [KeyboardButton("🌟 الصفقات الخاصة")],
        [KeyboardButton("📈 الأسعار الحية")],
        [KeyboardButton("🧠 تقرير التدريب والتعلم")], # خاص بالتعلم الخفي
        [KeyboardButton("💰 إدارة رأس المال")],
        [KeyboardButton("🌐 إدارة العملات")]
    ]
    # أزرار التشغيل والايقاف في الأسفل خاصة بالتعلم الخفي فقط
    bottom_row = [KeyboardButton("▶️ بدء التعلم الخفي"), KeyboardButton("⏸️ إيقاف التعلم الخفي")]
    
    markup = ReplyKeyboardMarkup(keyboard + [bottom_row], resize_keyboard=True)
    return markup

def get_private_trades_menu():
    """الأزرار الثلاثة المرتبطة بالصفقات الخاصة (تظهر عند الضغط على زر الصفقات الخاصة)"""
    keyboard = [
        [
            InlineKeyboardButton("🟢 تشغيل الإشارات", callback_data='elite_on'),
            InlineKeyboardButton("🔴 إيقاف الإشارات", callback_data='elite_off')
        ],
        [InlineKeyboardButton("📋 تقرير الأداء اللحظي", callback_data='elite_instant_report')],
        [InlineKeyboardButton("🔙 رجوع للقائمة الرئيسية", callback_data='main_menu')]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_coins_menu():
    keyboard = [
        [InlineKeyboardButton("➕ إضافة عملة جديدة", callback_data='add_coin')],
        [InlineKeyboardButton("➖ حذف عملة", callback_data='remove_coin')],
        [InlineKeyboardButton("📋 عرض الإعدادات", callback_data='view_coins')]
    ]
    return InlineKeyboardMarkup(keyboard)
