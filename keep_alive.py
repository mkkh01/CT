# keep_alive.py
from flask import Flask, request
from threading import Thread
import os
import asyncio

app = Flask(__name__)
telegram_app = None

@app.route('/')
def home():
    return "Institutional Trading Engine V5.0 is Running."

@app.route('/webhook', methods=['POST'])
def webhook():
    """استقبال التحديثات من تلجرام وتمريرها للبوت"""
    if telegram_app:
        asyncio.run_coroutine_threadsafe(
            telegram_app.update_queue.put(request.get_json()),
            telegram_app.loop
        )
    return 'OK', 200

def run():
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

def keep_alive(app_instance=None):
    global telegram_app
    telegram_app = app_instance
    t = Thread(target=run)
    t.daemon = True
    t.start()
