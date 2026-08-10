import os, re
from core.config import settings

supabase = None

try:
    from supabase import create_client
    raw_url = settings.SUPABASE_URL or ""
    key = settings.SUPABASE_KEY or ""

    # ✅ تحويل رابط PostgreSQL إلى رابط API تلقائياً
    if raw_url.startswith("postgresql://"):
        match = re.search(r"@([^:/]+)", raw_url)
        if match:
            host = match.group(1).replace(".pooler.", ".")
            raw_url = f"https://{host}"

    if raw_url.startswith("https://") and key:
        supabase = create_client(raw_url, key)
        print(f"✅ Supabase: متصل بنجاح")
    else:
        print(f"⚠️ بيانات Supabase غير مكتملة")

except Exception as e:
    print(f"❌ خطأ Supabase: {type(e).__name__}: {e}")
    supabase = None
