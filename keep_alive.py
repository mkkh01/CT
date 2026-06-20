# keep_alive.py
from flask import Flask, request
from threading import Thread
import os
import asyncio
import logging

logger = logging.getLogger(__name__)
app = Flask(__name__)
telegram_app = None

@app.route('/')
def home():
    return "Institutional Trading Engine V5.0 is Running."

@app.route('/webhook', methods=['POST'])
def webhook():
    """استقبال التحديثات من تلجرام وتمريرها للبوت"""
    global telegram_app
    if telegram_app:
        try:
            data = request.get_json()
            if data:
                # استخدام update_queue.put_nowait إذا كان متاحاً، أو تمرير التحديث بطريقة أخرى
                # ملاحظة: في النسخ الحديثة من python-telegram-bot، يفضل استخدام الطريقة الموصى بها للـ Webhooks
                if hasattr(telegram_app, 'update_queue') and telegram_app.update_queue is not None:
                    telegram_app.loop.call_soon_threadsafe(
                        telegram_app.update_queue.put_nowait, data
                    )
                    return 'OK', 200
                else:
                    # في حالة عدم استخدام Webhooks الرسمية، نكتفي بتسجيل الوصول
                    return 'OK (No Queue)', 200
        except Exception as e:
            logger.error(f"❌ [WEBHOOK ERROR] {e}")
            return 'Error', 500
    return 'Bot not ready', 503

def run():
    port = int(os.environ.get("PORT", 10000))
    # إخفاء سجلات Flask العادية لتقليل الضجيج
    log = logging.getLogger('werkzeug')
    log.setLevel(logging.ERROR)
    app.run(host='0.0.0.0', port=port, debug=False, use_reloader=False)

def keep_alive(app_instance=None):
    global telegram_app
    telegram_app = app_instance
    t = Thread(target=run, name="KeepAliveThread")
    t.daemon = True
    t.start()
    logger.info("🌐 [KEEP_ALIVE] Flask server started in background thread.")
