import os

os.environ["DISABLE_AUTO_START"] = "1"

from app.main import create_app


def test_dashboard_page_and_public_api(monkeypatch):
    monkeypatch.delenv("DASHBOARD_TOKEN", raising=False)
    app, runtime = create_app(start_runtime=False)
    client = app.test_client()

    assert client.get("/").status_code == 200
    assert client.get("/dashboard").status_code == 200
    response = client.get("/dashboard/api/overview")
    assert response.status_code == 200
    body = response.get_json()
    assert "overview" in body
    assert "recent_signals" in body
    assert body["overview"]["execution"] == "disabled"


def test_dashboard_ignores_legacy_token_header(monkeypatch):
    monkeypatch.setenv("DASHBOARD_TOKEN", "legacy-token")
    app, runtime = create_app(start_runtime=False)
    client = app.test_client()
    response = client.get("/dashboard/api/overview", headers={"X-Dashboard-Token": "wrong-token"})
    assert response.status_code == 200
    assert "overview" in response.get_json()
