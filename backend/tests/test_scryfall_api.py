from __future__ import annotations

from app.main import app
from fastapi.testclient import TestClient

client = TestClient(app)


def test_status_starts_not_started():
    resp = client.get("/api/scryfall/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "NOT_STARTED"
    assert body["card_count"] == 0
    assert body["error_message"] is None


def test_trigger_sync_marks_fetching_and_enqueues():
    resp = client.post("/api/scryfall/sync")
    assert resp.status_code == 202
    body = resp.json()
    assert body["status"] == "FETCHING"
    assert body["started_at"] is not None

    status = client.get("/api/scryfall/status").json()
    assert status["status"] == "FETCHING"


def test_trigger_sync_while_already_fetching_is_rejected():
    first = client.post("/api/scryfall/sync")
    assert first.status_code == 202

    second = client.post("/api/scryfall/sync")
    assert second.status_code == 409
