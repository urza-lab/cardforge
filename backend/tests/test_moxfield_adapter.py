from __future__ import annotations

import httpx
import pytest
from app.security.ssrf_guard import AuthRequiredError
from app.source_adapters import moxfield
from app.source_adapters.errors import InvalidUrlError, SourceFetchError

# Trimmed but structurally real sample (see app/source_adapters/moxfield.py
# docstring - shape confirmed against a real public deck during development).
SAMPLE_DECK = {
    "name": "Test Deck",
    "mainboard": {
        "Forest": {
            "quantity": 3,
            "isFoil": False,
            "card": {
                "name": "Forest",
                "scryfall_id": "43e7e6ec-9bfe-4062-a538-2a748d2eed1f",
                "set": "m20",
                "set_name": "Core Set 2020",
                "cn": "280",
            },
        },
        "Mana Crypt": {
            "quantity": 1,
            "isFoil": True,
            "card": {
                "name": "Mana Crypt",
                "scryfall_id": "480c2b30-c2c2-4b8b-ae0f-9f03732f92a1",
                "set": "eld",
                "set_name": "Throne of Eldraine",
                "cn": "331",
            },
        },
    },
    "sideboard": {},
    "maybeboard": {},
    "commanders": {
        "Atraxa, Praetors' Voice": {
            "quantity": 1,
            "isFoil": False,
            "card": {
                "name": "Atraxa, Praetors' Voice",
                "scryfall_id": "d0d33d52-3d28-4635-b985-51e126289259",
                "set": "znc",
                "set_name": "Zendikar Rising Commander",
                "cn": "1",
            },
        },
    },
    "companions": {},
}


def _response(status_code: int, json_body: object = None, headers: dict[str, str] | None = None) -> httpx.Response:
    request = httpx.Request("GET", "https://api.moxfield.com/v2/decks/all/x")
    kwargs: dict[str, object] = {"headers": headers or {}}
    if json_body is not None:
        import json

        return httpx.Response(status_code, content=json.dumps(json_body), request=request, **kwargs)
    return httpx.Response(status_code, request=request, **kwargs)


def test_validate_url_accepts_moxfield_deck_url():
    assert moxfield.validate_url("https://moxfield.com/decks/R3Nv7DlrokW5uPuriAGBng") is True


def test_validate_url_rejects_other_hosts():
    assert moxfield.validate_url("https://example.com/decks/abc") is False


def test_extract_deck_id_rejects_non_deck_paths():
    with pytest.raises(InvalidUrlError):
        moxfield.extract_deck_id("https://moxfield.com/users/someone")


def test_fetch_and_parse_maps_sections_and_fields(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(moxfield, "guarded_get", lambda url, **kwargs: _response(200, SAMPLE_DECK))
    fetch_result = moxfield.fetch_and_parse("https://moxfield.com/decks/abc123", user_agent="test-agent")
    result = fetch_result.parse_result

    assert result.error_rows == []
    assert len(result.valid_rows) == 3
    by_name = {row.mapped["name"]: row.mapped for row in result.valid_rows}
    assert by_name["Forest"]["quantity"] == 3
    assert by_name["Forest"]["section"] == "mainboard"
    assert by_name["Mana Crypt"]["foil"] is True
    assert by_name["Atraxa, Praetors' Voice"]["section"] == "commander"
    assert by_name["Atraxa, Praetors' Voice"]["scryfall_id"] == "d0d33d52-3d28-4635-b985-51e126289259"
    assert fetch_result.deck_name == "Test Deck"


def test_fetch_and_parse_raises_auth_required_on_403(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(moxfield, "guarded_get", lambda url, **kwargs: _response(403))
    with pytest.raises(AuthRequiredError):
        moxfield.fetch_and_parse("https://moxfield.com/decks/private-deck", user_agent="test-agent")


def test_fetch_and_parse_raises_source_fetch_error_on_404(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(moxfield, "guarded_get", lambda url, **kwargs: _response(404))
    with pytest.raises(SourceFetchError):
        moxfield.fetch_and_parse("https://moxfield.com/decks/does-not-exist", user_agent="test-agent")


def test_fetch_and_parse_bad_quantity_is_a_row_error(monkeypatch: pytest.MonkeyPatch):
    deck = {
        "mainboard": {"Bad Card": {"quantity": 0, "card": {"name": "Bad Card", "set": "m20", "cn": "1"}}},
        "sideboard": {},
        "maybeboard": {},
        "commanders": {},
        "companions": {},
    }
    monkeypatch.setattr(moxfield, "guarded_get", lambda url, **kwargs: _response(200, deck))
    fetch_result = moxfield.fetch_and_parse("https://moxfield.com/decks/abc", user_agent="test-agent")
    assert fetch_result.parse_result.rows[0].status == "error"
