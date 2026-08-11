from __future__ import annotations

import json

import httpx
import pytest
from app.security.ssrf_guard import AuthRequiredError
from app.source_adapters import archidekt
from app.source_adapters.errors import InvalidUrlError, SourceFetchError

# Trimmed but structurally real sample (see app/source_adapters/archidekt.py
# docstring - shape confirmed against a real public deck during development).
SAMPLE_DECK = {
    "name": "Test Deck",
    "cards": [
        {
            "quantity": 1,
            "categories": ["Commander"],
            "modifier": "Normal",
            "card": {
                "uid": "92b0be6d-9183-4938-b7a1-ae7f04ba78a0",
                "collectorNumber": "227",
                "edition": {"editioncode": "tsp", "editionname": "Time Spiral"},
                "oracleCard": {"name": "Thelon of Havenwood", "lang": "en"},
            },
        },
        {
            "quantity": 1,
            "categories": ["Maybeboard"],
            "modifier": "Foil",
            "card": {
                "uid": "480c2b30-c2c2-4b8b-ae0f-9f03732f92a1",
                "collectorNumber": "16",
                "edition": {"editioncode": "mps", "editionname": "Kaladesh Inventions"},
                "oracleCard": {"name": "Mana Crypt", "lang": "en"},
            },
        },
        {
            "quantity": 2,
            "categories": ["Ramp", "Custom Tag"],
            "modifier": "Normal",
            "card": {
                "uid": "de42a771-4f5c-4295-b070-8cb857a0279e",
                "collectorNumber": "56",
                "edition": {"editioncode": "mbs", "editionname": "Mirrodin Besieged"},
                "oracleCard": {"name": "Spread the Sickness", "lang": "en"},
            },
        },
    ]
}


def _response(status_code: int, json_body: object = None) -> httpx.Response:
    request = httpx.Request("GET", "https://archidekt.com/api/decks/1/")
    if json_body is not None:
        return httpx.Response(status_code, content=json.dumps(json_body), request=request)
    return httpx.Response(status_code, request=request)


def test_validate_url_accepts_archidekt_deck_url():
    assert archidekt.validate_url("https://archidekt.com/decks/1/fun_with_fungus") is True


def test_validate_url_rejects_non_numeric_id():
    assert archidekt.validate_url("https://archidekt.com/decks/abc") is False


def test_validate_url_rejects_other_hosts():
    assert archidekt.validate_url("https://example.com/decks/1") is False


def test_extract_deck_id_rejects_non_deck_paths():
    with pytest.raises(InvalidUrlError):
        archidekt.extract_deck_id("https://archidekt.com/users/someone")


def test_fetch_and_parse_maps_sections_categories_and_fields(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(archidekt, "guarded_get", lambda url, **kwargs: _response(200, SAMPLE_DECK))
    fetch_result = archidekt.fetch_and_parse("https://archidekt.com/decks/1/x", user_agent="test-agent")
    result = fetch_result.parse_result

    assert result.error_rows == []
    assert len(result.valid_rows) == 3
    by_name = {row.mapped["name"]: row.mapped for row in result.valid_rows}

    assert by_name["Thelon of Havenwood"]["section"] == "commander"
    assert by_name["Mana Crypt"]["section"] == "maybeboard"
    assert by_name["Mana Crypt"]["foil"] is True
    # "Ramp"/"Custom Tag" aren't recognized section categories - stay mainboard,
    # and get preserved as category/tags instead of being dropped.
    entry = by_name["Spread the Sickness"]
    assert entry["section"] == "mainboard"
    assert entry["category"] == "Ramp"
    assert entry["tags"] == ["Ramp", "Custom Tag"]
    assert entry["language"] == "EN"
    assert fetch_result.deck_name == "Test Deck"


def test_fetch_and_parse_raises_auth_required_on_401(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(archidekt, "guarded_get", lambda url, **kwargs: _response(401))
    with pytest.raises(AuthRequiredError):
        archidekt.fetch_and_parse("https://archidekt.com/decks/1/x", user_agent="test-agent")


def test_fetch_and_parse_raises_source_fetch_error_on_404(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(archidekt, "guarded_get", lambda url, **kwargs: _response(404))
    with pytest.raises(SourceFetchError):
        archidekt.fetch_and_parse("https://archidekt.com/decks/999999/x", user_agent="test-agent")


def test_fetch_and_parse_missing_cards_list_is_source_fetch_error(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(archidekt, "guarded_get", lambda url, **kwargs: _response(200, {"id": 1}))
    with pytest.raises(SourceFetchError):
        archidekt.fetch_and_parse("https://archidekt.com/decks/1/x", user_agent="test-agent")


def _search_response(results: list[dict[str, object]]) -> httpx.Response:
    request = httpx.Request("GET", "https://archidekt.com/api/decks/v3/")
    return httpx.Response(200, content=json.dumps({"count": len(results), "next": None, "results": results}), request=request)


def test_fetch_popular_decks_paginates_and_dedupes(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(archidekt.time, "sleep", lambda *_: None)
    calls: list[dict[str, object]] = []

    real_deck = {
        "id": 111, "name": "Real Deck", "owner": {"username": "Alice"},
        "viewCount": 5000, "colors": {"W": 10, "U": 20, "B": 0, "R": 0, "G": 0},
    }

    def fake_get(url: str, params: dict[str, object], headers: dict[str, str], timeout: float) -> httpx.Response:
        calls.append(dict(params))
        page = params["page"]
        if page == 1:
            return _search_response([real_deck])
        if page == 2:
            return _search_response([real_deck])  # same deck again - must dedupe
        return _search_response([])  # empty page - fetch stops early

    monkeypatch.setattr(archidekt.httpx, "get", fake_get)

    decks = archidekt.fetch_popular_decks("test-agent")

    assert len(calls) == 3  # stops as soon as an empty page is seen
    assert len(decks) == 1
    deck = decks[0]
    assert deck.external_id == "111"
    assert deck.name == "Real Deck"
    assert deck.author == "Alice"
    assert deck.source_url == "https://archidekt.com/decks/111"
    assert deck.view_count == 5000
    assert deck.like_count == 0
    assert deck.color_identity == ["W", "U"]


def test_fetch_popular_decks_raises_on_non_200(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(archidekt.time, "sleep", lambda *_: None)
    monkeypatch.setattr(
        archidekt.httpx,
        "get",
        lambda url, params, headers, timeout: httpx.Response(500, request=httpx.Request("GET", url)),
    )
    with pytest.raises(SourceFetchError):
        archidekt.fetch_popular_decks("test-agent")
