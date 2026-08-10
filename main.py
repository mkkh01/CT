import os, asyncio, logging
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
import uvicorn

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
log = logging.getLogger("main")
PORT = int(os.getenv("PORT", 8000))

app = FastAPI(title="CT Trading System v1.3")

from core.config import settings
from services.supabase_client import supabase
from services.redis_client import redis_client

# لوحة التحكم الرئيسية
@app.get("/", response_class=HTMLResponse)
def dashboard():
    mode = settings.MODE or "BALANCED"
    sb_status = "✅ متصل" if supabase else "❌ غير متصل"
    rd_status = "✅ متصل" if redis_client and redis_client.ping() else "❌ غير متصل"
    symbols_html = "".join([f"<span class='symbol'>{s}</span>" for s in settings.SYMBOLS])

    return f"""
    <!DOCTYPE html>
    <html dir="rtl">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>لوحة تحكم - نظام التداول</title>
        <style>
            * {{ margin:0; padding:0; box-sizing:border-box; font-family:system-ui, sans-serif; }}
            body {{ background:#0f172a; color:#f1f5f9; padding:20px; max-width:800px; margin:0 auto; }}
            h1 {{ text-align:center; color:#10b981; margin-bottom:30px; }}
            .card {{ background:#1e293b; border-radius:12px; padding:20px; margin-bottom:15px; }}
            .status {{ display:flex; align-items:center; gap:10px; font-size:18px; font-weight:bold; color:#10b981; }}
            .dot {{ width:12px; height:12px; background:#10b981; border-radius:50%; animation:blink 2s infinite; }}
            @keyframes blink {{ 0%,100% {{ opacity:1; }} 50% {{ opacity:0.3; }} }}
            .row {{ display:flex; justify-content:space-between; padding:10px 0; border-bottom:1px solid #334155; }}
            .row:last-child {{ border-bottom:none; }}
            .label {{ color:#94a3b8; }}
            .value {{ font-weight:bold; }}
            .symbols {{ display:flex; flex-wrap:wrap; gap:8px; margin-top:10px; }}
            .symbol {{ background:#3b82f6; padding:6px 12px; border-radius:6px; font-size:14px; }}
        </style>
    </head>
    <body>
        <h1>🤖 لوحة تحكم نظام التداول</h1>

        <div class="card">
            <div class="status"><span class="dot"></span> النظام يعمل ONLINE</div>
        </div>

        <div class="card">
            <div class="row"><span class="label">⚙️ وضع التداول</span><span class="value">{mode}</span></div>
            <div class="row"><span class="label">⏰ وقت العمل</span><span class="value">07:30 - 19:30 UTC</span></div>
            <div class="row"><span class="label">🔗 Supabase</span><span class="value">{sb_status}</span></div>
            <div class="row"><span class="label">⚡ Redis</span><span class="value">{rd_status}</span></div>
        </div>

        <div class="card">
            <div class="label">💰 العملات المراقبة</div>
            <div class="symbols">{symbols_html}</div>
        </div>

        <div class="card">
            <div class="label">📱 أوامر التليجرام</div>
            <div style="margin-top:10px; line-height:1.8;">
                /status - حالة النظام<br>
                /symbols - العملات<br>
                /mode - وضع التداول<br>
                /help - المساعدة
            </div>
        </div>
    </body>
    </html>
    """

@app.get("/health")
def health():
    return {
        "status": "ok",
        "system_online": settings.SYSTEM_ENABLED,
        "mode": settings.MODE or "BALANCED",
        "symbols": settings.SYMBOLS
    }

async def startup():
    log.info("✅ Supabase: %s", "connected" if supabase else "not configured")
    log.info("✅ Redis: %s", "connected" if redis_client and redis_client.ping() else "not connected")
    log.info("🚀 SYSTEM FULLY ONLINE ✅")

@app.on_event("startup")
async def on_start():
    await startup()
    try:
        from core.telegram_bot import TelegramBot
        tg = TelegramBot()
        await tg.start()
    except Exception as e:
        log.warning("🤖 Bot skipped: %s", e)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=PORT, log_level="info")
