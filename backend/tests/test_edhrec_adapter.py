from __future__ import annotations

import json

import httpx
import pytest
from app.source_adapters import edhrec
from app.source_adapters.errors import SourceFetchError


def _page_html(next_data: dict[str, object]) -> str:
    return f'<html><body><script id="__NEXT_DATA__" type="application/json">{json.dumps(next_data)}</script></body></html>'


def _response(status_code: int, html: str | None = None) -> httpx.Response:
    request = httpx.Request("GET", "https://edhrec.com/x")
    if html is not None:
        return httpx.Response(status_code, content=html, request=request)
    return httpx.Response(status_code, request=request)


def _commanders_page(cardviews: list[dict[str, object]]) -> str:
    return _page_html(
        {
            "props": {
                "pageProps": {
                    "data": {
                        "container": {
                            "json_dict": {
                                "cardlists": [{"header": "Past 2 Years", "tag": "past2years", "cardviews": cardviews}]
                            }
                        }
                    }
                }
            }
        }
    )


def _cv(name: str, num_decks: int) -> dict[str, object]:
    return {"name": name, "num_decks": num_decks}


def _commander_page(*, card: dict[str, object], counts: dict[str, int], cardlists: list[dict[str, object]]) -> str:
    return _page_html(
        {
            "props": {
                "pageProps": {
                    "data": {
                        **counts,
                        "container": {"json_dict": {"card": card, "cardlists": cardlists}},
                    }
                }
            }
        }
    )


def test_fetch_popular_commanders_parses_and_limits(monkeypatch: pytest.MonkeyPatch):
    cardviews = [
        {"sanitized": "cmdr-a", "name": "Commander A", "rank": 1, "num_decks": 500},
        {"sanitized": "cmdr-b", "name": "Commander B", "rank": 2, "num_decks": 400},
        {"sanitized": "cmdr-c", "name": "Commander C", "rank": 3, "num_decks": 300},
    ]
    monkeypatch.setattr(edhrec.httpx, "get", lambda url, **kw: _response(200, _commanders_page(cardviews)))

    result = edhrec.fetch_popular_commanders("test-agent", limit=2)
    assert [c.slug for c in result] == ["cmdr-a", "cmdr-b"]
    assert result[0].num_decks == 500


def test_fetch_popular_commanders_raises_when_no_next_data(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(edhrec.httpx, "get", lambda url, **kw: _response(200, "<html><body>nope</body></html>"))
    with pytest.raises(SourceFetchError):
        edhrec.fetch_popular_commanders("test-agent")


def test_fetch_popular_commanders_raises_on_non_200(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(edhrec.httpx, "get", lambda url, **kw: _response(500))
    with pytest.raises(SourceFetchError):
        edhrec.fetch_popular_commanders("test-agent")


def test_fetch_and_synthesize_builds_deck_from_real_shape(monkeypatch: pytest.MonkeyPatch):
    counts = {
        "creature": 2, "instant": 1, "sorcery": 0, "artifact": 2, "enchantment": 0,
        "battle": 0, "planeswalker": 0, "land": 5, "basic": 2, "nonbasic": 2,
    }
    card = {"name": "Test Commander", "color_identity": ["W", "U"]}
    cardlists = [
        {"tag": "creatures", "cardviews": [_cv("Creature A", 100), _cv("Creature B", 90), _cv("Creature C", 80)]},
        {"tag": "instants", "cardviews": [_cv("Instant A", 50)]},
        {"tag": "manaartifacts", "cardviews": [_cv("Mana Artifact A", 40)]},
        {"tag": "utilityartifacts", "cardviews": [_cv("Utility Artifact A", 60)]},
        {"tag": "lands", "cardviews": [_cv("Command Tower", 200), _cv("Plains", 190), _cv("Island", 180), _cv("Utility Land A", 30)]},
    ]
    monkeypatch.setattr(
        edhrec.httpx, "get", lambda url, **kw: _response(200, _commander_page(card=card, counts=counts, cardlists=cardlists))
    )

    commander = edhrec.CommanderRef(slug="test-commander", name="Test Commander", rank=1, num_decks=1000)
    entry = edhrec.fetch_and_synthesize(commander, "test-agent")

    lines = entry.deck_text.splitlines()
    assert lines[0] == "Commander: Test Commander"
    assert "Creature A" in lines and "Creature B" in lines
    assert "Creature C" not in lines  # only top 2 of 3 (creature target = 2)
    assert "Instant A" in lines
    # artifact target=2, combined mana+utility pool sorted by num_decks: Utility Artifact A (60) then Mana Artifact A (40)
    assert lines.count("Utility Artifact A") + lines.count("Mana Artifact A") == 2
    # nonbasic target=2, basics excluded from the lands pool
    assert "Command Tower" in lines
    assert "Utility Land A" in lines
    # basic target=2, WU identity -> 1 Plains + 1 Island synthesized directly (not from the lands cardlist pool)
    assert lines.count("Plains") == 1
    assert lines.count("Island") == 1
    assert entry.card_count == 2 + 1 + 2 + 2 + 2  # creature+instant+artifact+nonbasic+basic
    assert entry.color_identity == ["W", "U"]
    assert entry.commander_slug == "test-commander"


def test_fetch_and_synthesize_raises_on_missing_shape(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(edhrec.httpx, "get", lambda url, **kw: _response(200, _page_html({"props": {"pageProps": {"data": {}}}})))
    commander = edhrec.CommanderRef(slug="x", name="X", rank=1, num_decks=1)
    with pytest.raises(SourceFetchError):
        edhrec.fetch_and_synthesize(commander, "test-agent")


def test_fetch_and_synthesize_all_continues_past_one_failure(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(edhrec.time, "sleep", lambda *_: None)
    good_html = _commander_page(
        card={"name": "Good Commander", "color_identity": []},
        counts={"creature": 1, "instant": 0, "sorcery": 0, "artifact": 0, "enchantment": 0, "battle": 0,
                "planeswalker": 0, "land": 0, "basic": 0, "nonbasic": 0},
        cardlists=[{"tag": "creatures", "cardviews": [_cv("Only Creature", 10)]}],
    )

    def fake_get(url: str, **kw: object) -> httpx.Response:
        if "bad-commander" in url:
            return _response(500)
        return _response(200, good_html)

    monkeypatch.setattr(edhrec.httpx, "get", fake_get)

    commanders = [
        edhrec.CommanderRef(slug="good-commander", name="Good Commander", rank=1, num_decks=100),
        edhrec.CommanderRef(slug="bad-commander", name="Bad Commander", rank=2, num_decks=90),
    ]
    entries, errors = edhrec.fetch_and_synthesize_all(commanders, "test-agent")

    assert len(entries) == 1
    assert entries[0].commander_slug == "good-commander"
    assert len(errors) == 1
    assert "bad-commander" in errors[0]
