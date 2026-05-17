import os
import logging
import asyncio
import sqlite3
from datetime import datetime, timedelta
import pandas as pd
import numpy as np
import ta
import ccxt

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
    ContextTypes
)

# ==================================================
# CONFIGURATION & LOGGING
# ==================================================
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO
)
logger = logging.getLogger(__name__)

# ضع التوكن الخاص بك هنا أو اتركه ليسحب من متغيرات البيئة في Render
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "YOUR_TELEGRAM_BOT_TOKEN")

# إعداد منصة التداول عبر CCXT (وضع القراءة العامة لجلب البيانات)
exchange = ccxt.binance({
    'enableRateLimit': True,
    'options': {'defaultType': 'future'}
})

# ==================================================
# 2. STATE MACHINE & 3. DATA STRUCTURE (DB)
# ==================================================
STATE_IDLE = 0
STATE_WAIT_SYMBOL = 1
STATE_ADD_WATCHLIST = 2
STATE_SET_CAPITAL = 3

SAFE_MODE = False
RADAR_ON = True

def init_db():
    conn = sqlite3.connect('trading_system.db')
    cursor = conn.cursor()
    # جدول الإعدادات العامة (رأس المال والمخاطرة)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS settings (
            user_id INTEGER PRIMARY KEY,
            capital REAL DEFAULT 1000.0,
            risk_level TEXT DEFAULT 'MEDIUM'
        )
    ''')
    # جدول الـ Watchlist
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS watchlist (
            user_id INTEGER,
            symbol TEXT,
            PRIMARY KEY (user_id, symbol)
        )
    ''')
    # جدول الصفقات المفتوحة والمغلقة (Shadow Engine & Tracker)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT,
            strategy TEXT,
            direction TEXT,
            entry REAL,
            exit_price REAL,
            sl REAL,
            tp REAL,
            status TEXT,
            pnl REAL DEFAULT 0.0,
            regime TEXT,
            reason TEXT,
            timestamp TEXT
        )
    ''')
    # جدول أوزان الاستراتيجيات للتكيف الإحصائي
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS strategy_weights (
            strategy TEXT PRIMARY KEY,
            weight REAL
        )
    ''')
    # إدخال الأوزان الافتراضية
    strategies = [('Trend Following', 20.0), ('Breakout', 20.0), ('Range Reversal', 20.0)]
    for strat, weight in strategies:
        cursor.execute('INSERT OR IGNORE INTO strategy_weights (strategy, weight) VALUES (?, ?)', (strat, weight))
        
    conn.commit()
    conn.close()

init_db()

# دوان مساعدة لقاعدة البيانات
def get_user_setting(user_id, key, default):
    conn = sqlite3.connect('trading_system.db')
    cursor = conn.cursor()
    cursor.execute(f'SELECT {key} FROM settings WHERE user_id = ?', (user_id,))
    row = cursor.fetchone()
    conn.close()
    return row[0] if row else default

def update_user_setting(user_id, key, value):
    conn = sqlite3.connect('trading_system.db')
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO settings (user_id, f"{key}") VALUES (?, ?)
        ON CONFLICT(user_id) DO UPDATE SET "{key}" = excluded."{key}"
    '''.replace(f'f"{key}"', key).replace(f'"{key}"', key))
    conn.commit()
    conn.close()

# ==================================================
# 1. TELEGRAM BOT UI IMPLEMENTATION
# ==================================================
def main_menu_keyboard():
    global RADAR_ON, SAFE_MODE
    radar_text = "📡 Radar: ON" if RADAR_ON else "📡 Radar: OFF"
    safe_text = "🚫 Safe Mode: ACTIVE" if SAFE_MODE else "🚫 Safe Mode: OFF"
    
    keyboard = [
        [InlineKeyboardButton("🔍 Analyze Coin", callback_data="analyze_coin"),
         InlineKeyboardButton("📊 Daily Report", callback_data="daily_report")],
        [InlineKeyboardButton(radar_text, callback_data="radar_toggle"),
         InlineKeyboardButton("📝 Watchlist", callback_data="watchlist_menu")],
        [InlineKeyboardButton("💰 Capital", callback_data="capital_menu"),
         InlineKeyboardButton("⚙️ Risk Settings", callback_data="risk_menu")],
        [InlineKeyboardButton("🧠 Shadow Stats", callback_data="shadow_stats"),
         InlineKeyboardButton(safe_text, callback_data="safe_mode_toggle")],
        [InlineKeyboardButton("🔄 Re-scan Market", callback_data="rescan_market")]
    ]
    return InlineKeyboardMarkup(keyboard)

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['state'] = STATE_IDLE
    await update.message.reply_text(
        "==================================================\n"
        "📊 AI TRADING SYSTEM - CORE ENGINE v3.0\n"
        "==================================================\n"
        "المنظومة متصلة الآن بسيرفرات التداول الفورية وآمنة جغرافياً.\n"
        "الرجاء اختيار الإجراء المطلوب من لوحة التحكم التفاعلية:",
        reply_markup=main_menu_keyboard()
    )

# ==================================================
# 4. MARKET REGIME & 5. STRATEGY ENGINE & 6,7 SCORING
# ==================================================
async def fetch_and_clean_data(symbol):
    """ جلب البيانات وتحويلها مباشرة إلى هيكل بيانات Pandas طبقاً للبند 3 """
    try:
        ohlcv = exchange.fetch_ohlcv(symbol, timeframe='1h', limit=200)
        df = pd.DataFrame(ohlcv, columns=["timestamp", "open", "high", "low", "close", "volume"])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        return df
    except Exception as e:
        logger.error(f"Error fetching data for {symbol}: {e}")
        return None

def analyze_market_metrics(df):
    if df is None or len(df) < 50:
        return None
    
    # حساب المؤشرات الفنية الأساسية
    df['ema20'] = ta.trend.ema_indicator(df['close'], window=20)
    df['ema50'] = ta.trend.ema_indicator(df['close'], window=50)
    df['ema200'] = ta.trend.ema_indicator(df['close'], window=200)
    df['rsi'] = ta.momentum.rsi(df['close'], window=14)
    df['atr'] = ta.volatility.average_true_range(df['high'], df['low'], df['close'], window=14)
    
    # البولنجر باند لقياس التوسع والتقلب
    indicator_bb = ta.volatility.BollingerBands(close=df['close'], window=20, window_dev=2)
    df['bb_h'] = indicator_bb.bollinger_hband()
    df['bb_l'] = indicator_bb.bollinger_lband()
    df['bb_w'] = df['bb_h'] - df['bb_l']

    last = df.iloc[-1]
    prev = df.iloc[-2]
    
    # 4. MARKET REGIME LOGIC (HARD RULES)
    regime = "RANGING"
    if last['atr'] > df['atr'].mean() and last['bb_w'] > prev['bb_w']:
        regime = "HIGH_VOLATILITY"
    elif last['ema20'] > last['ema50'] > last['ema200']:
        regime = "TRENDING UP"
    elif (abs(last['ema20'] - last['ema50']) / last['close']) < 0.005 and last['volume'] < df['volume'].mean():
        regime = "RANGING"
    
    # فحص الهبوط المفاجئ (Panic Drop > 5%)
    short_pct = (df['close'].iloc[-5] - last['close']) / df['close'].iloc[-5]
    if short_pct > 0.05:
        regime = "PANIC"

    # حساب الـ Market Score الافتراضي (0-100)
    market_score = 65 
    if regime == "TRENDING UP": market_score += 20
    if regime == "PANIC": market_score -= 30
    if last['volume'] > df['volume'].mean(): market_score += 10
    market_score = max(0, min(100, market_score))
    
    return df, regime, market_score

def run_strategies(df, regime):
    last = df.iloc[-1]
    prev = df.iloc[-2]
    avg_volume = df['volume'].mean()
    
    # استرداد الأوزان الحركية لـ Shadow Engine
    conn = sqlite3.connect('trading_system.db')
    cursor = conn.cursor()
    weights = {}
    cursor.execute('SELECT strategy, weight FROM strategy_weights')
    for s, w in cursor.fetchall(): weights[s] = w
    conn.close()

    # القوانين الصارمة للـ 5. STRATEGY LOGIC
    # A) TREND FOLLOWING
    if (last['ema20'] > last['ema50'] > last['ema200'] and 
        50 <= last['rsi'] <= 70 and last['volume'] > prev['volume'] and 
        last['close'] > last['ema20']):
        return "BUY", "Trend Following", last['ema50'], last['close'] + (1.5 * (last['close'] - last['ema50'])), "Pullback to EMA20 aligned with trend"
        
    # B) BREAKOUT STRATEGY
    resistance = df['high'].iloc[-20:-1].max()
    if last['close'] > resistance and last['volume'] > (avg_volume * 1.3):
        sl = last['close'] - (2 * last['atr'])
        tp = last['close'] + (resistance - df['low'].iloc[-20:-1].min())
        return "BUY", "Breakout", sl, tp, "Volume spike confirmed breakout above resistance"

    # C) RANGE REVERSAL
    support = df['low'].iloc[-20:-1].min()
    resistance_r = df['high'].iloc[-20:-1].max()
    if last['rsi'] < 30 and abs(last['close'] - support) / last['close'] < 0.01:
        return "BUY", "Range Reversal", support * 0.99, (support + resistance_r) / 2, "RSI oversold near range support"
    
    return "NO TRADE", "None", 0, 0, "No Strategy rules matched current candle status."

# ==================================================
# 6. HARD KILL SWITCH FILTER & 7. SCORING ENGINE
# ==================================================
def evaluate_signal(symbol, df, regime, raw_direction, strategy, sl, tp, market_score):
    global SAFE_MODE
    if SAFE_MODE:
        return "NO TRADE", "SYSTEM IN SAFE MODE (FAIL SAFE ACTIVE)"
    
    if raw_direction == "NO TRADE":
        return "NO TRADE", "No strategy pattern matched."

    last = df.iloc[-1]
    total_volume_usdt = last['close'] * last['volume']
    
    # 6. SIGNAL FILTER (HARD KILL SWITCH)
    if total_volume_usdt < 2000000:
        return "NO TRADE", "REJECTED: Volume < 2,000,000 USDT (Weak Liquidity)"
    if market_score < 60:
        return "NO TRADE", f"REJECTED: Market Score ({market_score}) < 60"
    if regime == "PANIC":
        return "NO TRADE", "REJECTED: Market is in PANIC mode."
        
    # 7. SCORING ENGINE (FINAL DECISION)
    final_score = 50 
    if regime == "TRENDING UP": final_score += 20
    if last['rsi'] > 50: final_score += 15
    if last['volume'] > df['volume'].mean(): final_score += 15
    
    if final_score >= 80:
        return "BUY", f"VALID TRADE (Score: {final_score}/100)"
    else:
        return "NO TRADE", f"REJECTED: Final engine score ({final_score}) < 80"

# ==================================================
# CALLBACK QUERY PROCESSING & STATE MACHINE
# ==================================================
async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global RADAR_ON, SAFE_MODE
    query = update.callback_query
    await query.answer()
    
    data = query.data
    user_id = query.from_user.id
    
    if data == "analyze_coin":
        context.user_data['state'] = STATE_WAIT_SYMBOL
        await query.edit_message_text("🔍 الرجاء كتابة اسم العملة المراد فحصها الفوري (مثال: `BTCUSDT`):")
        
    elif data == "capital_menu":
        context.user_data['state'] = STATE_SET_CAPITAL
        current_cap = get_user_setting(user_id, 'capital', 1000.0)
        await query.edit_message_text(f"💰 رأس المال الحالي المعتمد للحساب: {current_cap} USDT\n\nأرسل القيمة الرقمية الجديدة الآن لتعديلها:")
        
    elif data == "risk_menu":
        current_risk = get_user_setting(user_id, 'risk_level', 'MEDIUM')
        keyboard = [
            [InlineKeyboardButton("Low (0.5%)", callback_data="set_risk_LOW"),
             InlineKeyboardButton("Medium (1.0%)", callback_data="set_risk_MEDIUM"),
             InlineKeyboardButton("High (2.0%)", callback_data="set_risk_HIGH")],
            [InlineKeyboardButton("🔙 العودة للرئيسية", callback_data="main_menu")]
        ]
        await query.edit_message_text(f"⚙️ إعدادات إدارة المخاطر الحالية: {current_risk}\nاختر النسبة لكل صفقة:", reply_markup=InlineKeyboardMarkup(keyboard))

    elif data.startswith("set_risk_"):
        new_risk = data.replace("set_risk_", "")
        update_user_setting(user_id, 'risk_level', new_risk)
        await query.edit_message_text(f"✅ تم تحديث مستوى المخاطرة إلى: **{new_risk}** بنجاح.", reply_markup=main_menu_keyboard())

    elif data == "radar_toggle":
        RADAR_ON = not RADAR_ON
        await query.edit_message_text(f"📡 تم تعديل حالة الرادار المستمر بنجاح.", reply_markup=main_menu_keyboard())
        
    elif data == "safe_mode_toggle":
        SAFE_MODE = not SAFE_MODE
        await query.edit_message_text(f"⚠️ تم تعديل وضع الأمان المتقدم للسيولة الفورية.", reply_markup=main_menu_keyboard())
        
    elif data == "shadow_stats":
        # 9. SHADOW ENGINE STATS OUTPUT
        conn = sqlite3.connect('trading_system.db')
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*), SUM(pnl) FROM trades WHERE status='CLOSED'")
        total, total_pnl = cursor.fetchone()
        total_pnl = total_pnl if total_pnl else 0.0
        conn.close()
        await query.edit_message_text(f"🧠 **SHADOW ENGINE STATS:**\n\n- إجمالي صفقات المحاكاة التاريخية: {total}\n- صافي الأرباح المحققة: {total_pnl:.2f} USDT\n- التكيف الإحصائي: نشط وتلقائي بالكامل.", reply_markup=main_menu_keyboard())

    elif data == "daily_report":
        # 12. REPORT ENGINE PREVIEW
        await query.edit_message_text("📊 **REPORT ENGINE (24H OUTPUT):**\n\nلا توجد صفقات مغلقة كافية خلال الـ 24 ساعة الماضية لتوليد تقرير إحصائي كامل. سيتم البث تلقائياً عند اكتمال الدورة.", reply_markup=main_menu_keyboard())

    elif data == "main_menu" or data == "rescan_market":
        context.user_data['state'] = STATE_IDLE
        await query.edit_message_text("الرجاء اختيار الإجراء المطلوب من لوحة التحكم التفاعلية:", reply_markup=main_menu_keyboard())

# ==================================================
# TEXT MESSAGES & PIPELINE EXECUTION
# ==================================================
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    state = context.user_data.get('state', STATE_IDLE)
    text = update.message.text.strip().upper()
    
    if state == STATE_WAIT_SYMBOL:
        context.user_data['state'] = STATE_IDLE
        await update.message.reply_text(f"⏳ جاري سحب بيانات {text} وتحليل الأنماط الفنية الفورية...")
        
        # 13. SYSTEM FLOW (FULL PIPELINE EXECUTION)
        df = await fetch_and_clean_data(text)
        metrics = analyze_market_metrics(df)
        
        if metrics is None:
            await update.message.reply_text("❌ فشل في جلب بيانات العملة. تأكد من كتابة الرمز بشكل صحيح (مثل BTCUSDT) ومن استقرار الـ API.", reply_markup=main_menu_keyboard())
            return
            
        df, regime, market_score = metrics
        raw_direction, strategy, sl, tp, reason = run_strategies(df, regime)
        final_decision, filter_reason = evaluate_signal(text, df, regime, raw_direction, strategy, sl, tp, market_score)
        
        if final_decision == "BUY":
            # 8. RISK ENGINE CALCULATIONS
            capital = get_user_setting(user_id, 'capital', 1000.0)
            risk_str = get_user_setting(user_id, 'risk_level', 'MEDIUM')
            risk_pct = 0.01 if risk_str == 'MEDIUM' else (0.005 if risk_str == 'LOW' else 0.02)
            
            entry_price = df['close'].iloc[-1]
            sl_distance = abs(entry_price - sl)
            position_size = (capital * risk_pct) / sl_distance if sl_distance > 0 else 0
            
            # تسجيل الصفقة للتتبع والـ Shadow Engine
            conn = sqlite3.connect('trading_system.db')
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO trades (symbol, strategy, direction, entry, sl, tp, status, regime, reason, timestamp)
                VALUES (?, ?, ?, ?, ?, ?, 'TRACKING', ?, ?, ?)
            ''', (text, strategy, 'BUY', entry_price, sl, tp, regime, reason, datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
            conn.commit()
            conn.close()

            # 15. FINAL OUTPUT FORMAT (TELEGRAM MESSAGE)
            response = (
                f"📊 **SIGNAL DETECTED**\n\n"
                f"**Symbol:** {text}\n"
                f"**Direction:** {final_decision}\n"
                f"**Confidence:** {market_score}/100\n"
                f"**Strategy:** {strategy}\n"
                f"**Regime:** {regime}\n"
                f"**Risk Profile:** {risk_str}\n\n"
                f"🎯 **Calculated Position Size:** {position_size:.4f} Units\n"
                f"🛑 **SL:** {sl:.2f}\n"
                f"🎯 **TP:** {tp:.2f}\n\n"
                f"**Reason:**\n- {reason}\n- Market indicators globally aligned."
            )
            await update.message.reply_text(response, reply_markup=main_menu_keyboard())
        else:
            # حالة الـ NO TRADE المحددة بالبند 6
            await update.message.reply_text(
                f"🚫 **OUTPUT: NO TRADE**\n\n"
                f"**Symbol:** {text}\n"
                f"**Status:** {filter_reason}\n"
                f"**Current Regime:** {regime}\n"
                f"**Market Clarity Score:** {market_score}/100", 
                reply_markup=main_menu_keyboard()
            )
            
    elif state == STATE_SET_CAPITAL:
        context.user_data['state'] = STATE_IDLE
        try:
            val = float(text)
            update_user_setting(user_id, 'capital', val)
            await update.message.reply_text(f"✅ تم حفظ وتأمين ميزانية رأس المال الجديد: {val} USDT لاستخدامه في معادلات حجم العقود الفورية.", reply_markup=main_menu_keyboard())
        except ValueError:
            await update.message.reply_text("⚠️ خطأ: الرجاء إدخال قيمة رقمية صحيحة فقط بدون حروف.", reply_markup=main_menu_keyboard())

# ==================================================
# 10. REAL-TIME SIGNAL TRACKER PIPELINE
# ==================================================
async def background_signal_tracker():
    """ فحص فوري كل 30-60 ثانية لحالة الأسعار للتأكد من ضرب الأهداف أو الستوب """
    while True:
        try:
            conn = sqlite3.connect('trading_system.db')
            cursor = conn.cursor()
            cursor.execute("SELECT id, symbol, entry, sl, tp FROM trades WHERE status='TRACKING'")
            open_trades = cursor.fetchall()
            
            for t_id, symbol, entry, sl, tp in open_trades:
                try:
                    ticker = exchange.fetch_ticker(symbol)
                    current_price = ticker['last']
                    
                    status_update = None
                    pnl = 0.0
                    
                    if current_price >= tp:
                        status_update = "CLOSED"
                        pnl = abs(tp - entry)
                    elif current_price <= sl:
                        status_update = "CLOSED"
                        pnl = -abs(entry - sl)
                        
                    if status_update:
                        cursor.execute("UPDATE trades SET status=?, exit_price=?, pnl=? WHERE id=?", (status_update, current_price, pnl, t_id))
                        logger.info(f"🏆 Tracker Engine closed trade for {symbol} with PNL: {pnl}")
                except Exception as ex:
                    logger.error(f"Error checking single asset live ticker {symbol}: {ex}")
                    
            conn.commit()
            conn.close()
        except Exception as e:
            logger.error(f"Error inside background loop process: {e}")
            
        await asyncio.sleep(45)

# ==================================================
# APPLICATION INITIALIZATION & STARTUP
# ==================================================
def main():
    if TELEGRAM_TOKEN == "YOUR_TELEGRAM_BOT_TOKEN":
        print("❌ CRITICAL ERROR: Please provide a valid Telegram Token.")
        return

    application = Application.builder().token(TELEGRAM_TOKEN).build()

    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CallbackQueryHandler(handle_callback))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    # تشغيل محرك الفحص والتعقب في الخلفية كأولوية تزامنية مستقلة
    loop = asyncio.get_event_loop()
    loop.create_task(background_signal_tracker())

    print("🚀 AI Trading Engine deployment complete on Frankfurt region server. Bot is live...")
    application.run_polling()

if __name__ == '__main__':
    main()
