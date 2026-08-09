from __future__ import annotations

from app.main import app
from fastapi.testclient import TestClient

client = TestClient(app)


def _default_collection_id() -> int:
    resp = client.get("/api/collections/default")
    id_: int = resp.json()["id"]
    return id_


def _import_lightning_bolt(collection_id: int, quantity: int = 2) -> None:
    content = f"Name,Quantity\nLightning Bolt,{quantity}\n".encode()
    preview = client.post(
        "/api/imports/preview",
        data={"source_type": "manabox_csv", "collection_id": str(collection_id)},
        files={"file": ("x.csv", content, "text/csv")},
    ).json()
    confirm = client.post(f"/api/imports/{preview['id']}/confirm", json={"skip_bad_rows": False})
    assert confirm.status_code == 200


def test_run_comparison_with_pasted_text():
    collection_id = _default_collection_id()
    _import_lightning_bolt(collection_id, quantity=4)

    resp = client.post(
        "/api/comparisons/run",
        data={"collection_id": str(collection_id), "source_type": "text_list", "text": "2 Lightning Bolt\n"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["is_fully_buildable"] is True
    assert body["row_errors"] == []


def test_run_comparison_reports_missing_cards():
    collection_id = _default_collection_id()
    _import_lightning_bolt(collection_id, quantity=1)

    resp = client.post(
        "/api/comparisons/run",
        data={"collection_id": str(collection_id), "source_type": "text_list", "text": "4 Lightning Bolt\n"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["is_fully_buildable"] is False
    assert body["missing"][0]["missing_quantity"] == 3


def test_run_comparison_with_file_upload():
    collection_id = _default_collection_id()
    _import_lightning_bolt(collection_id, quantity=2)

    resp = client.post(
        "/api/comparisons/run",
        data={"collection_id": str(collection_id), "source_type": "json"},
        files={"file": ("deck.json", b'{"cards": [{"name": "Lightning Bolt", "quantity": 2}]}', "application/json")},
    )
    assert resp.status_code == 200
    assert resp.json()["is_fully_buildable"] is True


def test_run_comparison_requires_text_or_file():
    collection_id = _default_collection_id()
    resp = client.post(
        "/api/comparisons/run", data={"collection_id": str(collection_id), "source_type": "text_list"}
    )
    assert resp.status_code == 400


def test_run_comparison_unknown_collection_404():
    resp = client.post(
        "/api/comparisons/run",
        data={"collection_id": "999999", "source_type": "text_list", "text": "1 Sol Ring\n"},
    )
    assert resp.status_code == 404


def test_run_comparison_rejects_manabox_source_type():
    collection_id = _default_collection_id()
    resp = client.post(
        "/api/comparisons/run",
        data={"collection_id": str(collection_id), "source_type": "manabox_csv", "text": "1 Sol Ring\n"},
    )
    assert resp.status_code == 400


def test_run_comparison_printing_mode():
    collection_id = _default_collection_id()
    _import_lightning_bolt(collection_id, quantity=1)

    resp = client.post(
        "/api/comparisons/run",
        data={
            "collection_id": str(collection_id),
            "source_type": "text_list",
            "text": "1 Lightning Bolt\n",
            "mode": "printing",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["mode"] == "printing"
    # No Scryfall sync has run against the test DB, so neither side resolves
    # to an exact printing - printing mode must honestly report it as missing.
    assert body["is_fully_buildable"] is False
