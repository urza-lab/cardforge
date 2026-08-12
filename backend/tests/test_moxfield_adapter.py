from __future__ import annotations

import json

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


def _search_response(decks: list[dict[str, object]]) -> httpx.Response:
    request = httpx.Request("GET", "https://api.moxfield.com/v2/decks/search")
    return httpx.Response(200, content=json.dumps({"data": decks}), request=request)


def test_fetch_popular_decks_paginates_both_sorts_and_dedupes(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(moxfield.time, "sleep", lambda *_: None)
    calls: list[dict[str, object]] = []

    shared = {
        "publicId": "shared-1", "name": "Shared Deck", "createdByUser": {"displayName": "Alice"},
        "publicUrl": "https://moxfield.com/decks/shared-1", "format": "commander",
        "viewCount": 500, "likeCount": 50, "colorIdentity": ["W", "U"],
    }

    def fake_get(url: str, params: dict[str, object], headers: dict[str, str], timeout: float) -> httpx.Response:
        calls.append(dict(params))
        unique = {
            "publicId": f"{params['sortType']}-{params['pageNumber']}",
            "name": "Unique", "createdByUser": {"displayName": "Bob"},
            "publicUrl": "https://moxfield.com/decks/unique", "format": "commander",
            "viewCount": 10, "likeCount": 1, "colorIdentity": [],
        }
        return _search_response([shared, unique])

    monkeypatch.setattr(moxfield.httpx, "get", fake_get)

    decks = moxfield.fetch_popular_decks("test-agent")

    expected_calls = len(moxfield.POPULAR_DECKS_SORTS) * moxfield.POPULAR_DECKS_PAGES_PER_SORT
    assert len(calls) == expected_calls
    assert {c["sortType"] for c in calls} == {"views", "likes"}
    # 1 shared deck (deduped across every response) + one page/sort-unique deck per call
    assert len(decks) == expected_calls + 1
    shared_result = next(d for d in decks if d.external_id == "shared-1")
    assert shared_result.name == "Shared Deck"
    assert shared_result.author == "Alice"
    assert shared_result.color_identity == ["W", "U"]
    assert shared_result.view_count == 500


def test_fetch_popular_decks_raises_on_non_200(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(moxfield.time, "sleep", lambda *_: None)
    monkeypatch.setattr(
        moxfield.httpx,
        "get",
        lambda url, params, headers, timeout: httpx.Response(429, request=httpx.Request("GET", url)),
    )
    with pytest.raises(SourceFetchError):
        moxfield.fetch_popular_decks("test-agent")


def test_fetch_popular_decks_extracts_new_real_fields(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(moxfield.time, "sleep", lambda *_: None)
    entry = {
        "publicId": "d1", "name": "Deck", "createdByUser": {"displayName": "Alice"},
        "publicUrl": "https://moxfield.com/decks/d1", "format": "commander",
        "viewCount": 1, "likeCount": 1, "colorIdentity": ["W"],
        "hasPrimer": True, "mainboardCount": 100, "commentCount": 12, "bookmarkCount": 3,
        "lastUpdatedAtUtc": "2026-03-15T09:21:30.92Z", "hubNames": ["Competitive"], "mainCardId": "E5bmd",
    }
    monkeypatch.setattr(moxfield.httpx, "get", lambda *a, **k: _search_response([entry]))

    decks = moxfield.fetch_popular_decks("test-agent")

    assert len(decks) == 1
    d = decks[0]
    assert d.has_primer is True
    assert d.deck_size == 100
    assert d.comment_count == 12
    assert d.bookmark_count == 3
    assert d.deck_updated_at is not None
    assert d.tags == ["Competitive"]
    assert d.main_card_id == "E5bmd"
    assert d.commander_name is None  # resolved separately, not by fetch_popular_decks itself


def _card_response(card_id: str, name: str | None, status_code: int = 200) -> httpx.Response:
    request = httpx.Request("GET", f"{moxfield.COMMANDER_LOOKUP_API}/{card_id}")
    if name is None:
        return httpx.Response(status_code, request=request)
    return httpx.Response(200, content=json.dumps({"card": {"id": card_id, "name": name}}), request=request)


def test_iter_resolved_commander_names_resolves_real_ids(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(moxfield.time, "sleep", lambda *_: None)
    names = {"E5bmd": "Winota, Joiner of Forces", "E1RzR": "Najeela, the Blade-Blossom"}

    def fake_get(url: str, headers: dict[str, str], timeout: float) -> httpx.Response:
        card_id = url.rsplit("/", 1)[-1]
        return _card_response(card_id, names.get(card_id))

    monkeypatch.setattr(moxfield.httpx, "get", fake_get)

    resolved = dict(moxfield.iter_resolved_commander_names({"E5bmd", "E1RzR"}, "test-agent"))
    assert resolved == names


def test_iter_resolved_commander_names_skips_known_and_bad_ids(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(moxfield.time, "sleep", lambda *_: None)
    calls: list[str] = []

    def fake_get(url: str, headers: dict[str, str], timeout: float) -> httpx.Response:
        card_id = url.rsplit("/", 1)[-1]
        calls.append(card_id)
        if card_id == "BADID":
            return _card_response(card_id, None, status_code=404)
        return _card_response(card_id, "Some Commander")

    monkeypatch.setattr(moxfield.httpx, "get", fake_get)

    resolved = dict(
        moxfield.iter_resolved_commander_names(
            {"KNOWN", "BADID", "NEW1"}, "test-agent", known={"KNOWN": "Already Cached"}
        )
    )

    assert "KNOWN" not in calls  # already known - never fetched
    assert resolved == {"NEW1": "Some Commander"}  # BADID's 404 is skipped, not raised
