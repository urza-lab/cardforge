from app.main import app
from fastapi.testclient import TestClient

client = TestClient(app)


def test_liveness():
    resp = client.get("/api/health/live")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert "uptime_seconds" in body


def test_root():
    resp = client.get("/api")
    assert resp.status_code == 200
    assert resp.json()["name"] == "CardForge"


def test_readiness_reports_degraded_without_db(monkeypatch):
    # Without a running Postgres/Redis, readiness must report degraded, not crash
    # and not silently claim success (no fake "always ok" health endpoint).
    resp = client.get("/api/health/ready")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] in ("ok", "degraded")
    assert "postgres" in body["checks"]
    assert "redis" in body["checks"]
