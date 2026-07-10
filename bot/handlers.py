import asyncio
import logging
from telegram import Update
from telegram.ext import ContextTypes, CommandHandler, MessageHandler, filters
from config.settings import ADMIN_ID
from config.constants import *
from bot.keyboards import get_main_menu, get_risk_menu

logger = logging.getLogger("CT_Handlers")

# Global reference to the bot engine (set in main.py)
bot_engine = None

def set_bot_engine(engine):
    global bot_engine
    bot_engine = engine

async def check_admin(update: Update) -> bool:
    return update.effective_user.id == ADMIN_ID

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_admin(update): return
    await update.message.reply_text(
        "👋 أهلاً بك في نظام التداول المؤسسي CT V4.0\nتم دمج محرك XAUBot AI بنجاح.",
        reply_markup=get_main_menu()
    )

async def handle_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_admin(update): return
    text = update.message.text
    
    if text == BUTTON_STATUS:
        await show_status(update, context)
    elif text == BUTTON_TRADES:
        await show_trades(update, context)
    elif text == BUTTON_SETTINGS:
        await show_settings(update, context)
    elif text == BUTTON_CAPITAL:
        await show_capital(update, context)
    elif text == BUTTON_RISK:
        await update.message.reply_text("⚠️ اختر مستوى المخاطرة:", reply_markup=get_risk_menu())
    elif text == BUTTON_LOGS:
        await show_logs(update, context)
    elif text == BUTTON_PERFORMANCE:
        await show_performance(update, context)
    elif text == BUTTON_START:
        await start_trading(update, context)
    elif text == BUTTON_STOP:
        await stop_trading(update, context)

async def show_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not bot_engine:
        await update.message.reply_text("❌ المحرك غير متصل.")
        return
    
    # Get status from XAUBot engine
    status = "متصل" if bot_engine._running else "متوقف"
    symbol = bot_engine.config.symbol
    capital = bot_engine.config.capital
    
    msg = (f"📊 *حالة النظام*\n"
           f"━━━━━━━━━━━━━━\n"
           f"🤖 المحرك: {status}\n"
           f"🪙 العملة: {symbol}\n"
           f"💰 رأس المال: {capital} USD\n"
           f"📈 الصفقات المفتوحة: {len(bot_engine.mt5.get_positions()) if not bot_engine.simulation else 0}")
    await update.message.reply_text(msg, parse_mode='Markdown')

async def start_trading(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if bot_engine:
        bot_engine._running = True
        await update.message.reply_text("▶️ تم تشغيل محرك التداول.")

async def stop_trading(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if bot_engine:
        bot_engine._running = False
        await update.message.reply_text("⏹ تم إيقاف محرك التداول.")

async def show_trades(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🔍 جاري جلب الصفقات المفتوحة من MT5...")
    # Logic to fetch from bot_engine.mt5

async def show_settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⚙️ إعدادات النظام الحالية...")

async def show_capital(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"💰 رأس المال الحالي: {bot_engine.config.capital if bot_engine else 0} USD")

async def show_logs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📋 آخر سجلات النظام...")

async def show_performance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📉 تقرير الأداء المؤسسي...")
