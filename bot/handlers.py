# bot/handlers.py
from telegram import Update
from telegram.ext import ContextTypes
from bot.keyboards import get_main_menu, get_coins_menu
from config import ADMIN_ID

async def check_admin(update: Update) -> bool:
    """حماية النظام: التأكد من أن المتحدث هو الأدمن"""
    user_id = update.effective_user.id
    if ADMIN_ID != 0 and user_id != ADMIN_ID:
        await update.message.reply_text("⛔ عذراً، أنت غير مصرح لك.")
        return False
    return True

async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """الرد على أمر /start"""
    if not await check_admin(update): return
    
    text = "🤖 *نظام التداول الخوارزمي الذكي*\n\nالأنظمة تعمل بكفاءة. اختر الإجراء:"
    await update.message.reply_text(text, reply_markup=get_main_menu(), parse_mode='Markdown')

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالجة الضغط على الأزرار"""
    query = update.callback_query
    await query.answer()
    
    if query.data == 'main_menu':
        await query.edit_message_text("لوحة التحكم الرئيسية:", reply_markup=get_main_menu())
    elif query.data == 'coins':
        await query.edit_message_text("🪙 *إدارة العملات*", reply_markup=get_coins_menu(), parse_mode='Markdown')
    elif query.data == 'report':
        await query.edit_message_text("📊 جاري تحليل صفقات التعلم من قاعدة البيانات...", reply_markup=get_main_menu())
