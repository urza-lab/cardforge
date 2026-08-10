from __future__ import annotations

import json

import httpx
import pytest
from app.main import app
from app.security.ssrf_guard import SsrfBlockedError
from app.source_adapters import moxfield
from fastapi.testclient import TestClient

client = TestClient(app)


def _create_list(name: str = "Test Deck") -> int:
    resp = client.post("/api/lists", json={"name": name, "list_type": "deck"})
    id_: int = resp.json()["id"]
    return id_


def _moxfield_response(status_code: int, json_body: object = None) -> httpx.Response:
    request = httpx.Request("GET", "https://api.moxfield.com/v2/decks/all/x")
    if json_body is not None:
        return httpx.Response(status_code, content=json.dumps(json_body), request=request)
    return httpx.Response(status_code, request=request)


_SAMPLE_MOXFIELD_DECK = {
    "name": "URL Test Deck",
    "mainboard": {
        "Sol Ring": {
            "quantity": 1,
            "isFoil": False,
            "card": {
                "name": "Sol Ring",
                "scryfall_id": "1f0d2e46-25e6-4415-8c00-53abaf7de520",
                "set": "c21",
                "set_name": "Commander 2021",
                "cn": "263",
            },
        },
    },
    "sideboard": {},
    "maybeboard": {},
    "commanders": {},
    "companions": {},
}


def test_text_preview_confirm_flow():
    list_id = _create_list()
    content = "4 Lightning Bolt\n1 Sol Ring\nCommander:\n1 Atraxa, Praetors' Voice\n"

    resp = client.post(
        "/api/list-imports/preview",
        data={"source_type": "text", "list_id": str(list_id)},
        files={"file": ("deck.txt", content.encode(), "text/plain")},
    )
    assert resp.status_code == 201
    preview = resp.json()
    assert preview["error_rows"] == 0
    assert preview["valid_rows"] == 3

    confirm = client.post(f"/api/list-imports/{preview['id']}/confirm", json={"skip_bad_rows": False})
    assert confirm.status_code == 200
    assert confirm.json()["status"] == "confirmed"
    assert confirm.json()["imported_rows"] == 3

    items = client.get(f"/api/lists/{list_id}/items").json()
    assert len(items) == 3
    commander = next(i for i in items if i["card_name"] == "Atraxa, Praetors' Voice")
    assert commander["section"] == "commander"
    mainboard_bolt = next(i for i in items if i["card_name"] == "Lightning Bolt")
    assert mainboard_bolt["section"] == "mainboard"
    assert mainboard_bolt["quantity"] == 4


def test_json_preview_confirm_flow_with_category_and_tags():
    list_id = _create_list("Cube Test")
    content = '{"cards": [{"name": "Sol Ring", "quantity": 1, "category": "Ramp", "tags": ["fast-mana"]}]}'

    preview = client.post(
        "/api/list-imports/preview",
        data={"source_type": "json", "list_id": str(list_id)},
        files={"file": ("cube.json", content.encode(), "application/json")},
    ).json()
    assert preview["error_rows"] == 0

    confirm = client.post(f"/api/list-imports/{preview['id']}/confirm", json={"skip_bad_rows": False})
    assert confirm.status_code == 200

    items = client.get(f"/api/lists/{list_id}/items").json()
    assert items[0]["category"] == "Ramp"
    assert items[0]["tags"] == ["fast-mana"]


def test_csv_preview_confirm_flow_with_section_category_tags():
    list_id = _create_list("CSV Cube Test")
    content = (
        "Name,Qty,Set Code,Section,Category,Tags\n"
        "Sol Ring,1,C21,,Ramp,fast-mana\n"
        "\"Atraxa, Praetors' Voice\",1,ZNC,commander,,\n"
    )

    preview = client.post(
        "/api/list-imports/preview",
        data={"source_type": "csv", "list_id": str(list_id)},
        files={"file": ("cube.csv", content.encode(), "text/csv")},
    ).json()
    assert preview["error_rows"] == 0
    assert preview["valid_rows"] == 2

    confirm = client.post(f"/api/list-imports/{preview['id']}/confirm", json={"skip_bad_rows": False})
    assert confirm.status_code == 200

    items = client.get(f"/api/lists/{list_id}/items").json()
    sol_ring = next(i for i in items if i["card_name"] == "Sol Ring")
    assert sol_ring["category"] == "Ramp"
    assert sol_ring["tags"] == ["fast-mana"]
    assert sol_ring["section"] == "mainboard"
    commander = next(i for i in items if "Atraxa" in i["card_name"])
    assert commander["section"] == "commander"


def test_csv_preview_with_explicit_column_mapping():
    list_id = _create_list("CSV Mapping Test")
    content = "MyCard,MyQty\nBlack Lotus,1\n"

    preview = client.post(
        "/api/list-imports/preview",
        data={
            "source_type": "csv",
            "list_id": str(list_id),
            "column_mapping": '{"name": "MyCard", "quantity": "MyQty"}',
        },
        files={"file": ("cube.csv", content.encode(), "text/csv")},
    ).json()
    assert preview["error_rows"] == 0
    assert preview["rows"][0]["mapped_data"]["name"] == "Black Lotus"


def test_csv_preview_invalid_column_mapping_json_400():
    list_id = _create_list()
    resp = client.post(
        "/api/list-imports/preview",
        data={"source_type": "csv", "list_id": str(list_id), "column_mapping": "not-json"},
        files={"file": ("cube.csv", b"Name,Qty\nSol Ring,1\n", "text/csv")},
    )
    assert resp.status_code == 400


def test_confirm_with_error_rows_requires_skip_bad_rows():
    list_id = _create_list()
    content = "4 Lightning Bolt\n0 Bad Quantity\n"

    preview = client.post(
        "/api/list-imports/preview",
        data={"source_type": "text", "list_id": str(list_id)},
        files={"file": ("deck.txt", content.encode(), "text/plain")},
    ).json()
    assert preview["error_rows"] == 1

    refused = client.post(f"/api/list-imports/{preview['id']}/confirm", json={"skip_bad_rows": False})
    assert refused.status_code == 400

    ok = client.post(f"/api/list-imports/{preview['id']}/confirm", json={"skip_bad_rows": True})
    assert ok.status_code == 200
    assert ok.json()["status"] == "partially_confirmed"


def test_abort_leaves_list_untouched():
    list_id = _create_list()
    content = "1 Abort Me\n"

    preview = client.post(
        "/api/list-imports/preview",
        data={"source_type": "text", "list_id": str(list_id)},
        files={"file": ("deck.txt", content.encode(), "text/plain")},
    ).json()

    aborted = client.post(f"/api/list-imports/{preview['id']}/abort")
    assert aborted.status_code == 200
    assert aborted.json()["status"] == "aborted"

    items = client.get(f"/api/lists/{list_id}/items").json()
    assert items == []

    resp = client.post(f"/api/list-imports/{preview['id']}/confirm", json={"skip_bad_rows": False})
    assert resp.status_code == 409


def test_duplicate_upload_is_flagged_after_confirm():
    list_id = _create_list()
    content = "1 Sol Ring\n"

    first = client.post(
        "/api/list-imports/preview",
        data={"source_type": "text", "list_id": str(list_id)},
        files={"file": ("deck.txt", content.encode(), "text/plain")},
    ).json()
    client.post(f"/api/list-imports/{first['id']}/confirm", json={"skip_bad_rows": False})

    second = client.post(
        "/api/list-imports/preview",
        data={"source_type": "text", "list_id": str(list_id)},
        files={"file": ("deck.txt", content.encode(), "text/plain")},
    ).json()
    assert second["is_likely_duplicate"] is True
    assert second["duplicate_of_import_id"] == first["id"]


def test_preview_unknown_source_type_400():
    list_id = _create_list()
    resp = client.post(
        "/api/list-imports/preview",
        data={"source_type": "manabox_csv", "list_id": str(list_id)},
        files={"file": ("x.txt", b"1 Sol Ring\n", "text/plain")},
    )
    assert resp.status_code == 400


def test_preview_unknown_list_404():
    resp = client.post(
        "/api/list-imports/preview",
        data={"source_type": "text", "list_id": "999999"},
        files={"file": ("x.txt", b"1 Sol Ring\n", "text/plain")},
    )
    assert resp.status_code == 404


def test_imported_items_are_resolved_against_scryfall():
    from app.core.database import get_sessionmaker
    from app.models.scryfall import ScryfallCard

    db = get_sessionmaker()()
    try:
        db.add(
            ScryfallCard(
                id="e3285e6b-3e79-4d7c-bf96-d920f973b122",
                oracle_id="4457ed35-7c10-48c8-9776-456485fdf070",
                name="Lightning Bolt",
                set_code="LEA",
                set_name="Limited Edition Alpha",
                collector_number="161",
                lang="en",
                layout="normal",
            )
        )
        db.commit()
    finally:
        db.close()

    list_id = _create_list()
    preview = client.post(
        "/api/list-imports/preview",
        data={"source_type": "text", "list_id": str(list_id)},
        files={"file": ("deck.txt", b"1 Lightning Bolt\n", "text/plain")},
    ).json()
    client.post(f"/api/list-imports/{preview['id']}/confirm", json={"skip_bad_rows": False})

    items = client.get(f"/api/lists/{list_id}/items").json()
    assert items[0]["resolved_oracle_id"] == "4457ed35-7c10-48c8-9776-456485fdf070"


def test_url_preview_confirm_sets_list_source(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(moxfield, "guarded_get", lambda url, **kwargs: _moxfield_response(200, _SAMPLE_MOXFIELD_DECK))

    list_id = _create_list("URL Deck")
    preview = client.post(
        "/api/list-imports/preview-url",
        json={"list_id": list_id, "url": "https://moxfield.com/decks/abc123"},
    )
    assert preview.status_code == 201
    body = preview.json()
    assert body["source_type"] == "moxfield"
    assert body["source_url"] == "https://moxfield.com/decks/abc123"
    assert body["original_filename"] is None
    assert body["valid_rows"] == 1

    confirm = client.post(f"/api/list-imports/{body['id']}/confirm", json={"skip_bad_rows": False})
    assert confirm.status_code == 200

    card_list = client.get(f"/api/lists/{list_id}").json()
    assert card_list["source_type"] == "moxfield"
    assert card_list["source_url"] == "https://moxfield.com/decks/abc123"

    items = client.get(f"/api/lists/{list_id}/items").json()
    assert items[0]["card_name"] == "Sol Ring"


def test_url_preview_unsupported_url_400():
    list_id = _create_list()
    resp = client.post(
        "/api/list-imports/preview-url",
        json={"list_id": list_id, "url": "https://example.com/decks/abc"},
    )
    assert resp.status_code == 400


def test_url_preview_unknown_list_404(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(moxfield, "guarded_get", lambda url, **kwargs: _moxfield_response(200, _SAMPLE_MOXFIELD_DECK))
    resp = client.post(
        "/api/list-imports/preview-url",
        json={"list_id": 999999, "url": "https://moxfield.com/decks/abc123"},
    )
    assert resp.status_code == 404


def test_url_preview_ssrf_blocked_400(monkeypatch: pytest.MonkeyPatch):
    def _raise(url: str, **kwargs: object) -> httpx.Response:
        raise SsrfBlockedError(f"'{url}' resolves to a blocked address")

    monkeypatch.setattr(moxfield, "guarded_get", _raise)
    list_id = _create_list()
    resp = client.post(
        "/api/list-imports/preview-url",
        json={"list_id": list_id, "url": "https://moxfield.com/decks/abc123"},
    )
    assert resp.status_code == 400
    assert "URL rejected" in resp.json()["detail"]


def test_url_preview_auth_required_401(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(moxfield, "guarded_get", lambda url, **kwargs: _moxfield_response(403))
    list_id = _create_list()
    resp = client.post(
        "/api/list-imports/preview-url",
        json={"list_id": list_id, "url": "https://moxfield.com/decks/abc123"},
    )
    assert resp.status_code == 401


def test_url_preview_source_fetch_error_502(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(moxfield, "guarded_get", lambda url, **kwargs: _moxfield_response(404))
    list_id = _create_list()
    resp = client.post(
        "/api/list-imports/preview-url",
        json={"list_id": list_id, "url": "https://moxfield.com/decks/abc123"},
    )
    assert resp.status_code == 502
