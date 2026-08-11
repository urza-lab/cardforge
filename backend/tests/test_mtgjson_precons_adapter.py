from __future__ import annotations

import httpx
import pytest
from app.source_adapters import mtgjson_precons
from app.source_adapters.errors import SourceFetchError


def _response(status_code: int, json_body: object | None = None) -> httpx.Response:
    request = httpx.Request("GET", "https://mtgjson.com/x")
    if json_body is not None:
        import json

        return httpx.Response(status_code, content=json.dumps(json_body), request=request)
    return httpx.Response(status_code, request=request)


def _deck_list_payload(entries: list[dict[str, object]]) -> dict[str, object]:
    return {"data": entries}


def _card(name: str, oracle_id: str | None, scryfall_id: str | None = None, count: int = 1) -> dict[str, object]:
    return {"name": name, "count": count, "identifiers": {"scryfallOracleId": oracle_id, "scryfallId": scryfall_id}}


def _deck_payload(*, name: str, commander: list[dict], main_board: list[dict]) -> dict[str, object]:
    return {"data": {"name": name, "commander": commander, "mainBoard": main_board}}


def test_fetch_precon_decks_filters_to_commander_type_and_builds_csv(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(mtgjson_precons.time, "sleep", lambda *_: None)

    deck_list = _deck_list_payload(
        [
            {"fileName": "GoodCommanderDeck", "name": "Good Commander Deck", "type": "Commander Deck", "releaseDate": "2024-01-01", "source": "https://example.com/good"},
            {"fileName": "SomeThemeDeck", "name": "Some Theme Deck", "type": "Theme Deck", "releaseDate": "2020-01-01"},
        ]
    )
    deck = _deck_payload(
        name="Good Commander Deck",
        commander=[_card("Urza, Chief Artificer", "aaaa-oracle", "aaaa-scryfall")],
        main_board=[
            _card("Baleful Strix", "bbbb-oracle", "bbbb-scryfall", count=1),
            _card("Island", "cccc-oracle", "cccc-scryfall", count=5),
        ],
    )

    def fake_get(url: str, **kw: object) -> httpx.Response:
        if url == mtgjson_precons.DECK_LIST_URL:
            return _response(200, deck_list)
        return _response(200, deck)

    monkeypatch.setattr(mtgjson_precons.httpx, "get", fake_get)

    entries, errors = mtgjson_precons.fetch_precon_decks("test-agent")

    assert errors == []
    assert len(entries) == 1
    entry = entries[0]
    assert entry.file_name == "GoodCommanderDeck"
    assert entry.commander_names == ["Urza, Chief Artificer"]
    assert entry.card_count == 1 + 1 + 5
    assert entry.cards == [
        {"name": "Urza, Chief Artificer", "oracle_id": "aaaa-oracle", "quantity": 1},
        {"name": "Baleful Strix", "oracle_id": "bbbb-oracle", "quantity": 1},
        {"name": "Island", "oracle_id": "cccc-oracle", "quantity": 5},
    ]
    lines = entry.deck_text.splitlines()
    assert lines[0] == "name,quantity,scryfall_id,section"
    assert '"Urza, Chief Artificer",1,aaaa-scryfall,commander' in lines
    assert "Baleful Strix,1,bbbb-scryfall,mainboard" in lines
    assert "Island,5,cccc-scryfall,mainboard" in lines


def test_fetch_precon_decks_raises_on_deck_list_failure(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(mtgjson_precons.httpx, "get", lambda url, **kw: _response(500))
    with pytest.raises(SourceFetchError):
        mtgjson_precons.fetch_precon_decks("test-agent")


def test_fetch_precon_decks_raises_when_no_commander_decks(monkeypatch: pytest.MonkeyPatch):
    deck_list = _deck_list_payload([{"fileName": "X", "name": "X", "type": "Theme Deck"}])
    monkeypatch.setattr(mtgjson_precons.httpx, "get", lambda url, **kw: _response(200, deck_list))
    with pytest.raises(SourceFetchError):
        mtgjson_precons.fetch_precon_decks("test-agent")


def test_fetch_precon_decks_continues_past_one_deck_failure(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(mtgjson_precons.time, "sleep", lambda *_: None)
    deck_list = _deck_list_payload(
        [
            {"fileName": "GoodDeck", "name": "Good Deck", "type": "Commander Deck"},
            {"fileName": "BadDeck", "name": "Bad Deck", "type": "Commander Deck"},
        ]
    )
    good_deck = _deck_payload(
        name="Good Deck",
        commander=[_card("Commander A", "oracle-a")],
        main_board=[_card("Card A", "oracle-b")],
    )

    def fake_get(url: str, **kw: object) -> httpx.Response:
        if url == mtgjson_precons.DECK_LIST_URL:
            return _response(200, deck_list)
        if "BadDeck" in url:
            return _response(500)
        return _response(200, good_deck)

    monkeypatch.setattr(mtgjson_precons.httpx, "get", fake_get)

    entries, errors = mtgjson_precons.fetch_precon_decks("test-agent")

    assert len(entries) == 1
    assert entries[0].file_name == "GoodDeck"
    assert len(errors) == 1
    assert "BadDeck" in errors[0]


def test_fetch_precon_decks_skips_deck_missing_commander_or_mainboard(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(mtgjson_precons.time, "sleep", lambda *_: None)
    deck_list = _deck_list_payload([{"fileName": "EmptyDeck", "name": "Empty Deck", "type": "Commander Deck"}])
    empty_deck = _deck_payload(name="Empty Deck", commander=[], main_board=[_card("Card A", "oracle-a")])

    def fake_get(url: str, **kw: object) -> httpx.Response:
        if url == mtgjson_precons.DECK_LIST_URL:
            return _response(200, deck_list)
        return _response(200, empty_deck)

    monkeypatch.setattr(mtgjson_precons.httpx, "get", fake_get)

    entries, errors = mtgjson_precons.fetch_precon_decks("test-agent")

    assert entries == []
    assert len(errors) == 1
    assert "EmptyDeck" in errors[0]
