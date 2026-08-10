from core.config import settings

db_conn = None

async def init_db():
    global db_conn
    db_url = settings.SUPABASE_URL or ""
    
    if not db_url.startswith("postgresql://"):
        print("⚠️ رابط PostgreSQL غير صالح")
        return None

    try:
        import psycopg
        db_conn = await psycopg.AsyncConnection.connect(db_url)
        print("✅ Supabase PostgreSQL: متصل بنجاح ✅")
        return db_conn
    except Exception as e:
        print(f"❌ خطأ قاعدة البيانات: {type(e).__name__}: {e}")
        return None

async def close_db():
    global db_conn
    if db_conn:
        await db_conn.close()
        print("✅ تم إغلاق اتصال قاعدة البيانات")
