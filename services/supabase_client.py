import os, re
from core.config import settings

supabase = None

try:
    from supabase import create_client
    raw_url = settings.SUPABASE_URL or ""
    key = settings.SUPABASE_KEY or ""

    # تحويل رابط PostgreSQL إلى رابط REST API
    if raw_url.startswith("postgresql://"):
        m = re.search(r"@([^:/]+)", raw_url)
        if m:
            host = m.group(1).replace(".pooler.", ".")
            raw_url = f"https://{host}"

    if raw_url.startswith("https://") and key and not key.startswith("sb_secret_"):
        supabase = create_client(raw_url, key)
        log_msg = f"✅ Supabase: متصل"
    elif key.startswith("sb_secret_"):
        log_msg = "⚠️ Supabase: استخدم مفتاح Service Role (يبدأ بـ eyJhbGci...), وليس sb_secret_..."
    else:
        log_msg = f"⚠️ Supabase: بيانات غير مكتملة"

    print(log_msg)
except Exception as e:
    print(f"❌ Supabase خطأ: {e}")
    supabase = None
