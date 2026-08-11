from __future__ import annotations

from app.main import app
from fastapi.testclient import TestClient

client = TestClient(app)


def test_get_settings_returns_seeded_defaults():
    resp = client.get("/api/settings")
    assert resp.status_code == 200
    body = resp.json()
    assert body["default_comparison_mode"] == "oracle"
    assert body["preferred_currency"] == "USD"


def test_update_comparison_mode():
    resp = client.put("/api/settings", json={"default_comparison_mode": "printing"})
    assert resp.status_code == 200
    assert resp.json()["default_comparison_mode"] == "printing"

    assert client.get("/api/settings").json()["default_comparison_mode"] == "printing"


def test_update_preferred_currency_is_uppercased():
    resp = client.put("/api/settings", json={"preferred_currency": "chf"})
    assert resp.status_code == 200
    assert resp.json()["preferred_currency"] == "CHF"


def test_partial_update_leaves_other_field_untouched():
    client.put("/api/settings", json={"preferred_currency": "EUR"})
    resp = client.put("/api/settings", json={"default_comparison_mode": "printing"})
    assert resp.json()["preferred_currency"] == "EUR"
    assert resp.json()["default_comparison_mode"] == "printing"


def test_invalid_comparison_mode_rejected():
    resp = client.put("/api/settings", json={"default_comparison_mode": "nonsense"})
    assert resp.status_code == 400


def test_grafana_embed_url_starts_unset():
    assert client.get("/api/settings").json()["grafana_embed_url"] is None


def test_grafana_embed_url_can_be_set_and_cleared():
    url = "http://docker.trusted.local:3000/public-dashboards/abc123"
    resp = client.put("/api/settings", json={"grafana_embed_url": url})
    assert resp.status_code == 200
    assert resp.json()["grafana_embed_url"] == url
    assert client.get("/api/settings").json()["grafana_embed_url"] == url

    cleared = client.put("/api/settings", json={"grafana_embed_url": None})
    assert cleared.json()["grafana_embed_url"] is None


def test_grafana_embed_url_omitted_leaves_it_untouched():
    url = "http://docker.trusted.local:3000/public-dashboards/xyz789"
    client.put("/api/settings", json={"grafana_embed_url": url})
    resp = client.put("/api/settings", json={"preferred_currency": "EUR"})
    assert resp.json()["grafana_embed_url"] == url
