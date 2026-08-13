from app.config import Settings


def test_postgres_supabase_url_is_rejected(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "postgresql://user:password@pooler.supabase.com:6543/postgres")
    settings = Settings.from_env()
    assert settings.supabase_url == ""
    assert "PostgreSQL connection string" in settings.supabase_url_issue
    assert any("PostgreSQL connection string" in item for item in settings.missing_integrations())
