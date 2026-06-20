# keep_alive.py
from flask import Flask
from threading import Thread
import os
import logging

# إعداد السجلات لـ Flask
logger = logging.getLogger(__name__)

app = Flask(__name__)

@app.route('/')
def home():
    return "Institutional Trading Engine V5.0 is Running."

def run():
    port = int(os.environ.get("PORT", 10000))
    # إخفاء سجلات Flask العادية لتقليل الضجيج
    log = logging.getLogger('werkzeug')
    log.setLevel(logging.ERROR)
    
    # استخدام debug=False و use_reloader=False ضروري جداً لمنع تشغيل نسخة ثانية من main.py
    try:
        app.run(host='0.0.0.0', port=port, debug=False, use_reloader=False)
    except Exception as e:
        logger.error(f"❌ [KEEP_ALIVE] Flask server error: {e}")

def keep_alive(app_instance=None):
    """
    تشغيل خادم Flask في Thread منفصل لضمان بقاء الخدمة حية على منصات الاستضافة.
    """
    t = Thread(target=run, name="KeepAliveThread", daemon=True)
    t.start()
    logger.info("🌐 [KEEP_ALIVE] Flask server started in background thread.")
