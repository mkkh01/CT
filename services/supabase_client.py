import os, re, sys
from core.config import settings

supabase = None

try:
    # ✅ تجاوز خطأ websockets.asyncio
    import websockets
    if not hasattr(websockets, 'asyncio'):
        websockets.asyncio = None

    from supabase import create_client
    raw_url = settings.SUPABASE_URL or ""
    key = settings.SUPABASE_KEY or ""

    # تحويل رابط PostgreSQL إلى رابط API
    if raw_url.startswith("postgresql://"):
        m = re.search(r"@([^:/]+)", raw_url)
        if m:
            host = m.group(1).replace(".pooler.", ".")
            raw_url = f"https://{host}"

    if raw_url.startswith("https://") and key:
        supabase = create_client(raw_url, key)
        print(f"✅ Supabase: متصل بنجاح")
    else:
        print(f"⚠️ Supabase: بيانات غير مكتملة")

except Exception as e:
    print(f"⚠️ Supabase: مؤجل — {type(e).__name__}")
    print(f"   النظام يعمل بدونها حالياً")
    supabase = None
