from core.config import settings
try:
    from supabase import create_client, Client
    supabase: Client = create_client(settings.SUPABASE_URL, settings.SUPABASE_KEY) if settings.SUPABASE_URL and settings.SUPABASE_KEY else None
except Exception:
    supabase = None
