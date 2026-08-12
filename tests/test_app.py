import os

os.environ["DISABLE_AUTO_START"] = "1"

from app.main import create_app


def test_health_endpoints_are_available_without_starting_runtime(monkeypatch):
    monkeypatch.setenv("DASHBOARD_TOKEN", "test-dashboard-token")
    app, runtime = create_app(start_runtime=False)
    client = app.test_client()
    response = client.get("/healthz")
    assert response.status_code == 200
    body = response.get_json()
    assert body["status"] == "ok"
    index = client.get("/", follow_redirects=False)
    assert index.status_code == 200
    assert "CT Trading Monitor" in index.get_data(as_text=True)
    assert "Location" not in index.headers
    heartbeat = client.get("/cron/heartbeat", follow_redirects=False)
    assert heartbeat.status_code == 200
    assert heartbeat.get_json()["status"] == "ok"
    assert "Location" not in heartbeat.headers
    assert client.get("/api/status").status_code == 200
    assert client.get("/api/snapshot").status_code == 401
    assert client.get("/api/snapshot", headers={"X-Dashboard-Token": "test-dashboard-token"}).status_code == 200
