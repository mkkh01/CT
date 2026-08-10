import os
from core.config import settings

supabase = None

try:
    from supabase import create_client
    url = settings.SUPABASE_URL or ""
    key = settings.SUPABASE_KEY or ""
    
    if url.startswith("postgresql://"):
        # رابط قاعدة بيانات مباشر — نحول لـ REST API
        import re
        match = re.search(r"@([^/]+)/", url)
        if match:
            host = match.group(1).replace(".pooler.", ".").replace(":6543","")
            url = f"https://{host}"
    
    if url and key and url.startswith("https://"):
        supabase = create_client(url, key)
        print(f"✅ Supabase: متصل بـ {url}")
    else:
        print(f"⚠️ Supabase: بيانات غير مكتملة — URL={bool(url)}, KEY={bool(key)}")
except Exception as e:
    print(f"❌ Supabase خطأ: {e}")
    supabase = None
