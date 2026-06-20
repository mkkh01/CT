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

# تم إيقاف مسار الـ Webhook لتجنب التعارض مع نظام الـ Polling
# @app.route('/webhook', methods=['POST'])
# def webhook():
#     ...

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
