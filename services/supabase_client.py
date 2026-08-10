from core.config import settings

db_conn = None
supabase = None

async def init_db():
    global db_conn, supabase
    db_url = settings.SUPABASE_URL or ""
    if not db_url.startswith("postgresql://"):
        print("⚠️ رابط PostgreSQL غير صالح")
        return None
    try:
        import psycopg
        db_conn = await psycopg.AsyncConnection.connect(db_url)
        supabase = db_conn
        print("✅ Supabase PostgreSQL: متصل بنجاح ✅")
        return db_conn
    except Exception as e:
        print(f"❌ خطأ قاعدة البيانات: {type(e).__name__}: {e}")
        return None

async def close_db():
    global db_conn, supabase
    if db_conn:
        await db_conn.close()
        print("✅ تم إغلاق اتصال قاعدة البيانات")
