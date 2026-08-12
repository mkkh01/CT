import os

os.environ["DISABLE_AUTO_START"] = "1"

from app.main import create_app


def test_dashboard_page_and_protected_api(monkeypatch):
    monkeypatch.setenv("DASHBOARD_TOKEN", "test-dashboard-token")
    app, runtime = create_app(start_runtime=False)
    client = app.test_client()

    assert client.get("/dashboard").status_code == 200
    assert client.get("/dashboard/api/overview").status_code == 401
    response = client.get("/dashboard/api/overview", headers={"X-Dashboard-Token": "test-dashboard-token"})
    assert response.status_code == 200
    body = response.get_json()
    assert "overview" in body
    assert "recent_signals" in body
    assert body["overview"]["execution"] == "disabled"


def test_dashboard_requires_token_when_not_configured(monkeypatch):
    monkeypatch.delenv("DASHBOARD_TOKEN", raising=False)
    app, runtime = create_app(start_runtime=False)
    client = app.test_client()
    assert client.get("/dashboard/api/overview").status_code == 503
