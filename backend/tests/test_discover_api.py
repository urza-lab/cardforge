from __future__ import annotations

import pytest
from app.core.database import get_sessionmaker
from app.main import app
from app.models.discover import PopularDeck
from app.parsers.common import ParsedRow, ParseResult
from app.services import pricing_service
from app.source_adapters import moxfield
from app.source_adapters.common import DeckFetchResult
from fastapi.testclient import TestClient

client = TestClient(app)


def _seed_deck(**overrides: object) -> None:
    defaults: dict[str, object] = {
        "source": "moxfield",
        "external_id": "abc",
        "name": "Test Deck",
        "author": "Alice",
        "source_url": "https://moxfield.com/decks/abc",
        "format": "commander",
        "view_count": 100,
        "like_count": 10,
        "color_identity": ["W", "U"],
    }
    defaults.update(overrides)
    db = get_sessionmaker()()
    try:
        db.add(PopularDeck(**defaults))
        db.commit()
    finally:
        db.close()


def test_status_starts_not_started():
    resp = client.get("/api/discover/decks/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "NOT_STARTED"
    assert body["deck_count"] == 0


def test_trigger_sync_marks_fetching_and_enqueues():
    resp = client.post("/api/discover/decks/sync")
    assert resp.status_code == 202
    assert resp.json()["status"] == "FETCHING"

    second = client.post("/api/discover/decks/sync")
    assert second.status_code == 409


def test_list_decks_empty():
    resp = client.get("/api/discover/decks")
    assert resp.status_code == 200
    assert resp.json() == []


def test_list_decks_sorted_by_views_and_likes():
    _seed_deck(external_id="a", name="A", view_count=50, like_count=200)
    _seed_deck(external_id="b", name="B", view_count=500, like_count=20)

    by_views = client.get("/api/discover/decks?sort=views").json()
    assert [d["name"] for d in by_views] == ["B", "A"]

    by_likes = client.get("/api/discover/decks?sort=likes").json()
    assert [d["name"] for d in by_likes] == ["A", "B"]


def test_list_decks_color_identity_filter():
    _seed_deck(external_id="mono-w", name="Mono W", color_identity=["W"])
    _seed_deck(external_id="wu", name="WU Deck", color_identity=["W", "U"])
    _seed_deck(external_id="wubrg", name="Five Color", color_identity=["W", "U", "B", "R", "G"])

    resp = client.get("/api/discover/decks?color_identity=WU").json()
    names = {d["name"] for d in resp}
    assert names == {"Mono W", "WU Deck"}  # subset-of-WU matches; 5c deck doesn't


def test_list_decks_source_filter():
    _seed_deck(external_id="mox-1", name="Mox Deck", source="moxfield")
    _seed_deck(external_id="ark-1", name="Ark Deck", source="archidekt")

    resp = client.get("/api/discover/decks?source=archidekt").json()
    assert [d["name"] for d in resp] == ["Ark Deck"]


def test_list_decks_bracket_filter():
    _seed_deck(external_id="no-bracket", name="No Bracket", bracket=None)
    _seed_deck(external_id="bracket-3", name="Bracket 3", bracket=3)
    _seed_deck(external_id="bracket-4", name="Bracket 4", bracket=4)

    resp = client.get("/api/discover/decks?bracket=3").json()
    assert [d["name"] for d in resp] == ["Bracket 3"]

    unfiltered = client.get("/api/discover/decks").json()
    assert len(unfiltered) == 3


def test_list_decks_name_search_case_insensitive_substring():
    _seed_deck(external_id="winota", name="Winota: Snowball Stax")
    _seed_deck(external_id="najeela", name="Najeela Warrior Queen")

    resp = client.get("/api/discover/decks?q=snowball").json()
    assert [d["name"] for d in resp] == ["Winota: Snowball Stax"]

    resp = client.get("/api/discover/decks?q=WINOTA").json()
    assert [d["name"] for d in resp] == ["Winota: Snowball Stax"]

    resp = client.get("/api/discover/decks?q=doesnotexist").json()
    assert resp == []


def test_list_decks_name_search_matches_commander_name_too():
    _seed_deck(external_id="winota", name="Some Weird Deck Name", commander_name="Winota, Joiner of Forces")
    _seed_deck(external_id="other", name="Other Deck", commander_name="Najeela, the Blade-Blossom")

    resp = client.get("/api/discover/decks?q=winota").json()
    assert [d["name"] for d in resp] == ["Some Weird Deck Name"]


def test_list_decks_has_primer_filter():
    _seed_deck(external_id="primer", name="Has Primer", has_primer=True)
    _seed_deck(external_id="no-primer", name="No Primer", has_primer=False)

    resp = client.get("/api/discover/decks?has_primer=true").json()
    assert [d["name"] for d in resp] == ["Has Primer"]


def test_list_decks_min_deck_size_filter():
    _seed_deck(external_id="full", name="Full Deck", deck_size=100)
    _seed_deck(external_id="partial", name="Partial Deck", deck_size=42)
    _seed_deck(external_id="unknown", name="Unknown Size", deck_size=None)

    resp = client.get("/api/discover/decks?min_deck_size=100").json()
    assert [d["name"] for d in resp] == ["Full Deck"]


def test_list_decks_exclude_theorycrafted_filter():
    _seed_deck(external_id="real", name="Real Deck", theorycrafted=False)
    _seed_deck(external_id="theory", name="Theory Deck", theorycrafted=True)
    _seed_deck(external_id="unknown", name="Moxfield Deck", theorycrafted=None)

    resp = client.get("/api/discover/decks?exclude_theorycrafted=true").json()
    names = {d["name"] for d in resp}
    assert names == {"Real Deck", "Moxfield Deck"}  # unknown (Moxfield) is never excluded, only a real True is

    unfiltered = client.get("/api/discover/decks").json()
    assert len(unfiltered) == 3


def test_list_decks_updated_after_days_filter():
    from datetime import UTC, datetime, timedelta

    _seed_deck(external_id="fresh", name="Fresh Deck", deck_updated_at=datetime.now(UTC))
    _seed_deck(external_id="stale", name="Stale Deck", deck_updated_at=datetime.now(UTC) - timedelta(days=400))
    _seed_deck(external_id="unknown", name="No Timestamp", deck_updated_at=None)

    resp = client.get("/api/discover/decks?updated_after_days=30").json()
    assert [d["name"] for d in resp] == ["Fresh Deck"]


def test_list_decks_tag_filter():
    _seed_deck(external_id="tagged", name="Competitive Deck", tags=["Competitive"])
    _seed_deck(external_id="other-tag", name="Budget Deck", tags=["Budget"])
    _seed_deck(external_id="no-tags", name="Untagged Deck", tags=None)

    resp = client.get("/api/discover/decks?tag=Competitive").json()
    assert [d["name"] for d in resp] == ["Competitive Deck"]


def test_list_decks_normalizes_malformed_tag_assignment_objects():
    """Real bug found live: some already-stored PopularDeck rows have
    `tags` as a list of Archidekt tag-assignment objects (dicts with an
    "id"/"tag"/"name"/"position" shape), not plain strings - this crashed
    the whole endpoint with a 500 (Pydantic validation error) regardless of
    which row in the result set had it. See app/schemas/discover.py's
    PopularDeckRead validator and CLAUDE.md.
    """
    _seed_deck(
        external_id="malformed-tags",
        name="Malformed Tags Deck",
        tags=[{"id": 1, "tag": 33, "deck": 111, "name": "Sacrifice", "position": "M-500000"}, "PlainStringTag"],
    )

    resp = client.get("/api/discover/decks")
    assert resp.status_code == 200
    body = resp.json()
    assert body[0]["tags"] == ["Sacrifice", "PlainStringTag"]


def test_list_decks_sort_by_comments_and_bookmarks():
    _seed_deck(external_id="a", name="A", comment_count=5, bookmark_count=50)
    _seed_deck(external_id="b", name="B", comment_count=50, bookmark_count=5)

    by_comments = client.get("/api/discover/decks?sort=comments").json()
    assert [d["name"] for d in by_comments] == ["B", "A"]

    by_bookmarks = client.get("/api/discover/decks?sort=bookmarks").json()
    assert [d["name"] for d in by_bookmarks] == ["A", "B"]


def test_archidekt_commander_search_proxies_live_and_intersects_cache(monkeypatch: pytest.MonkeyPatch):
    from app.source_adapters import archidekt

    _seed_deck(external_id="111", name="Cached Winota Deck", source="archidekt")
    # A live result the API returns but this project hasn't cached (never
    # synced) - must be silently excluded, not fabricated into a thin row.
    monkeypatch.setattr(archidekt, "search_by_commander", lambda commander, user_agent: {"111", "999-not-cached"})

    resp = client.get("/api/discover/decks/archidekt-commander-search?commander=Winota")
    assert resp.status_code == 200
    body = resp.json()
    assert [d["name"] for d in body] == ["Cached Winota Deck"]


def test_archidekt_commander_search_empty_query_returns_empty():
    resp = client.get("/api/discover/decks/archidekt-commander-search?commander=")
    assert resp.status_code == 200
    assert resp.json() == []


def test_archidekt_commander_search_upstream_failure_is_502(monkeypatch: pytest.MonkeyPatch):
    from app.source_adapters import archidekt
    from app.source_adapters.errors import SourceFetchError

    def raise_error(commander: str, user_agent: str) -> set[str]:
        raise SourceFetchError("Archidekt commander search returned HTTP 500")

    monkeypatch.setattr(archidekt, "search_by_commander", raise_error)

    resp = client.get("/api/discover/decks/archidekt-commander-search?commander=Winota")
    assert resp.status_code == 502


def test_price_deck_caches_result_and_returns_it(monkeypatch: pytest.MonkeyPatch):
    _seed_deck(external_id="price-me", name="Price Me")
    db = get_sessionmaker()()
    try:
        profile = pricing_service.get_or_create_default_price_profile(db)
        profile_id = profile.id
    finally:
        db.close()

    parse_result = ParseResult(
        rows=[
            ParsedRow(
                row_number=1,
                raw={"name": "Some Card"},
                mapped={
                    "name": "Some Card", "quantity": 1, "set_code": None, "collector_number": None,
                    "language": None, "scryfall_id": None,
                },
            )
        ]
    )
    monkeypatch.setattr(
        moxfield, "fetch_and_parse", lambda url, user_agent: DeckFetchResult(deck_name="Price Me", parse_result=parse_result)
    )

    decks = client.get("/api/discover/decks").json()
    deck_id = next(d["id"] for d in decks if d["name"] == "Price Me")
    assert decks[0]["priced_at"] is None

    resp = client.post(f"/api/discover/decks/{deck_id}/price", json={"price_profile_id": profile_id})
    assert resp.status_code == 200
    body = resp.json()
    assert body["priced_at"] is not None
    assert body["coverage_percent"] == 0.0
    assert body["unpriced_missing_count"] == 1  # "Some Card" has no price observation seeded

    refetched = client.get("/api/discover/decks").json()
    assert refetched[0]["priced_at"] is not None  # cached, no re-fetch needed to see it


def test_price_deck_404_for_unknown_deck():
    db = get_sessionmaker()()
    try:
        profile_id = pricing_service.get_or_create_default_price_profile(db).id
    finally:
        db.close()

    resp = client.post("/api/discover/decks/999999/price", json={"price_profile_id": profile_id})
    assert resp.status_code == 404


def test_price_deck_404_for_unknown_price_profile():
    _seed_deck(external_id="no-profile", name="No Profile")
    db = get_sessionmaker()()
    try:
        deck_id = db.query(PopularDeck).filter_by(external_id="no-profile").one().id
    finally:
        db.close()

    resp = client.post(f"/api/discover/decks/{deck_id}/price", json={"price_profile_id": 999999})
    assert resp.status_code == 404
