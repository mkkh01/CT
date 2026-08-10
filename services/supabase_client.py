import os, re
from core.config import settings

supabase = None

try:
    from supabase import create_client
    raw_url = settings.SUPABASE_URL or ""
    key = settings.SUPABASE_KEY or ""

    # ✅ تحويل رابط PostgreSQL إلى رابط API
    if raw_url.startswith("postgresql://"):
        match = re.search(r"@([^:/]+)", raw_url)
        if match:
            host = match.group(1).replace(".pooler.", ".")
            raw_url = f"https://{host}"

    # ✅ تقبل المفتاح سواء كان eyJhbGci... أو sb_secret...
    if raw_url.startswith("https://") and key:
        try:
            supabase = create_client(raw_url, key)
            print(f"✅ Supabase: متصل بنجاح")
        except Exception as api_err:
            # ✅ إذا فشل بـ API → نستخدم رابط PostgreSQL مباشرة
            import psycopg
            db_url = settings.SUPABASE_URL
            conn = psycopg.connect(db_url)
            print(f"✅ Supabase: متصل عبر PostgreSQL مباشرة")
            supabase = conn
    else:
        print(f"⚠️ بيانات غير مكتملة")

except Exception as e:
    print(f"❌ خطأ Supabase: {type(e).__name__}: {e}")
    supabase = None
