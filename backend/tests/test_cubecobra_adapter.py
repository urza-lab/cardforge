from __future__ import annotations

import httpx
import pytest
from app.security.ssrf_guard import AuthRequiredError
from app.source_adapters import cubecobra
from app.source_adapters.errors import InvalidUrlError, SourceFetchError

# Trimmed but structurally real sample (see app/source_adapters/cubecobra.py
# docstring - header row and column names confirmed against a real cube's
# CSV export during development).
SAMPLE_CSV = (
    "name,CMC,Type,Color,Set,Collector Number,Rarity,Color Category,status,Finish,board,maybeboard,"
    "image URL,image Back URL,tags,Notes,MTGO ID,Custom,Voucher,Artist\r\n"
    '"Sol Ring",1,"Artifact",,"c21","263",uncommon,null,"Not Owned","Non-foil","mainboard",false,,,'
    '"","",12345,false,false,"Artist A"\r\n'
    '"Mana Crypt",0,"Artifact",,"eld","331",mythic,null,"Not Owned","Foil","mainboard",false,,,'
    '"fast-mana","",67890,false,false,"Artist B"\r\n'
)


def _response(status_code: int, text: str | None = None) -> httpx.Response:
    request = httpx.Request("GET", "https://cubecobra.com/cube/download/csv/x")
    if text is not None:
        return httpx.Response(status_code, content=text, request=request)
    return httpx.Response(status_code, request=request)


def _search_response(cubes: list[dict[str, object]], last_key: object | None = None) -> httpx.Response:
    request = httpx.Request("POST", "https://cubecobra.com/search/getmoresearchitems")
    import json

    return httpx.Response(200, content=json.dumps({"success": "true", "cubes": cubes, "lastKey": last_key}), request=request)


def test_validate_url_accepts_cubecobra_cube_url():
    assert cubecobra.validate_url("https://cubecobra.com/cube/list/modovintage") is True


def test_validate_url_accepts_overview_url_too():
    assert cubecobra.validate_url("https://cubecobra.com/cube/overview/abc123") is True


def test_validate_url_rejects_other_hosts():
    assert cubecobra.validate_url("https://example.com/cube/list/abc") is False


def test_extract_cube_id_rejects_non_cube_paths():
    with pytest.raises(InvalidUrlError):
        cubecobra.extract_cube_id("https://cubecobra.com/user/someone")


def test_fetch_and_parse_maps_fields(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(cubecobra, "guarded_get", lambda url, **kwargs: _response(200, SAMPLE_CSV))
    fetch_result = cubecobra.fetch_and_parse("https://cubecobra.com/cube/list/modovintage", user_agent="test-agent")
    result = fetch_result.parse_result

    assert result.error_rows == []
    assert len(result.valid_rows) == 2
    by_name = {row.mapped["name"]: row.mapped for row in result.valid_rows}
    assert by_name["Sol Ring"]["quantity"] == 1
    assert by_name["Sol Ring"]["foil"] is False
    assert by_name["Sol Ring"]["set_code"] == "C21"
    assert by_name["Sol Ring"]["section"] == "mainboard"
    assert by_name["Mana Crypt"]["foil"] is True
    assert by_name["Mana Crypt"]["tags"] == ["fast-mana"]
    assert fetch_result.deck_name is None


def test_fetch_and_parse_tolerates_malformed_row_with_extra_columns(monkeypatch: pytest.MonkeyPatch):
    """Real bug found live: a free-text "Notes" cell on CubeCobra's own
    export with an unescaped quote character shifts every later column on
    that one row, so csv.DictReader stashes the overflow under a `None`
    key - csv.DictWriter used to raise on that and abort the *whole*
    cube's import over a single bad row, even though every field this
    adapter actually maps (name/Set/Collector Number/Finish/board/tags)
    sits earlier in the row than where the real export breaks.
    """
    malformed_csv = (
        "name,CMC,Type,Color,Set,Collector Number,Rarity,Color Category,status,Finish,board,maybeboard,"
        "image URL,image Back URL,tags,Notes,MTGO ID,Custom,Voucher,Artist\r\n"
        '"Ornithopter",0,"Artifact Creature",,"mrd","224",uncommon,Colorless,"Owned","Non-foil","mainboard",false,,,'
        '"","Cube Commonwealth Indy KC" -- an unescaped quote shifts everything after this,12345,false,false,'
        'Dana Knutson\r\n'
        '"Sol Ring",1,"Artifact",,"c21","263",uncommon,null,"Not Owned","Non-foil","mainboard",false,,,'
        '"","",12345,false,false,"Artist A"\r\n'
    )
    monkeypatch.setattr(cubecobra, "guarded_get", lambda url, **kwargs: _response(200, malformed_csv))

    fetch_result = cubecobra.fetch_and_parse("https://cubecobra.com/cube/list/modovintage", user_agent="test-agent")
    result = fetch_result.parse_result

    assert result.error_rows == []
    by_name = {row.mapped["name"]: row.mapped for row in result.valid_rows}
    assert "Ornithopter" in by_name
    assert by_name["Ornithopter"]["set_code"] == "MRD"
    assert by_name["Ornithopter"]["section"] == "mainboard"
    assert "Sol Ring" in by_name  # a later, well-formed row still parses fine too


def test_fetch_and_parse_raises_auth_required_on_403(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(cubecobra, "guarded_get", lambda url, **kwargs: _response(403))
    with pytest.raises(AuthRequiredError):
        cubecobra.fetch_and_parse("https://cubecobra.com/cube/list/private-cube", user_agent="test-agent")


def test_fetch_and_parse_raises_source_fetch_error_on_404(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(cubecobra, "guarded_get", lambda url, **kwargs: _response(404))
    with pytest.raises(SourceFetchError):
        cubecobra.fetch_and_parse("https://cubecobra.com/cube/list/does-not-exist", user_agent="test-agent")


def test_fetch_and_parse_raises_on_non_csv_response(monkeypatch: pytest.MonkeyPatch):
    # A private/removed cube redirects to a normal 200 HTML error page rather
    # than a 404 - see the adapter's own real-CSV-header sanity check.
    monkeypatch.setattr(cubecobra, "guarded_get", lambda url, **kwargs: _response(200, "<html>not a csv</html>"))
    with pytest.raises(SourceFetchError):
        cubecobra.fetch_and_parse("https://cubecobra.com/cube/list/private-cube", user_agent="test-agent")


def test_fetch_popular_cubes_paginates_via_last_key(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(cubecobra.time, "sleep", lambda *_: None)
    calls: list[dict[str, object]] = []

    page1_cube = {
        "id": "abc-1", "shortId": "topcube", "name": "Top Cube", "owner": {"username": "Alice"},
        "cardCount": 360, "likeCount": 500, "tags": ["legacy"],
    }
    page2_cube = {
        "id": "abc-2", "shortId": "secondcube", "name": "Second Cube", "owner": {"username": "Bob"},
        "cardCount": 540, "likeCount": 200, "tags": None,
    }

    def fake_post(url: str, json: dict[str, object], headers: dict[str, str], timeout: float) -> httpx.Response:
        calls.append(dict(json))
        if json["lastKey"] is None:
            return _search_response([page1_cube], last_key={"PK": "next"})
        if json["lastKey"] == {"PK": "next"}:
            return _search_response([page2_cube], last_key=None)
        return _search_response([])

    monkeypatch.setattr(cubecobra.httpx, "post", fake_post)

    cubes = cubecobra.fetch_popular_cubes("test-agent", pages=5)

    assert len(calls) == 2  # stops once lastKey comes back None
    assert [c.short_id for c in cubes] == ["topcube", "secondcube"]
    assert cubes[0].source_url == "https://cubecobra.com/cube/list/topcube"
    assert cubes[0].owner_username == "Alice"
    assert cubes[0].like_count == 500
    assert cubes[1].tags is None


def test_fetch_popular_cubes_raises_on_non_200(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(cubecobra.time, "sleep", lambda *_: None)
    monkeypatch.setattr(
        cubecobra.httpx,
        "post",
        lambda url, json, headers, timeout: httpx.Response(500, request=httpx.Request("POST", url)),
    )
    with pytest.raises(SourceFetchError):
        cubecobra.fetch_popular_cubes("test-agent", pages=3)


def test_iter_all_cubes_walks_past_any_fixed_page_count(monkeypatch: pytest.MonkeyPatch):
    """The real point of this generator over fetch_popular_cubes: it must
    keep walking lastKey until CubeCobra itself says there's nothing left,
    not stop at any particular page count - see CLAUDE.md for the real
    0-like cube this was built to eventually reach.
    """
    monkeypatch.setattr(cubecobra.time, "sleep", lambda *_: None)
    total_pages = 7
    calls: list[dict[str, object]] = []

    def fake_post(url: str, json: dict[str, object], headers: dict[str, str], timeout: float) -> httpx.Response:
        calls.append(dict(json))
        page_num = len(calls)
        cube = {"id": f"cube-{page_num}", "shortId": f"slug-{page_num}", "name": f"Cube {page_num}"}
        last_key = {"PK": f"page-{page_num}"} if page_num < total_pages else None
        return _search_response([cube], last_key=last_key)

    monkeypatch.setattr(cubecobra.httpx, "post", fake_post)

    pages = list(cubecobra.iter_all_cubes("test-agent"))

    assert len(calls) == total_pages
    assert len(pages) == total_pages
    assert [p[0].external_id for p in pages] == [f"cube-{i}" for i in range(1, total_pages + 1)]


def test_iter_all_cubes_yields_incrementally_as_pages_are_fetched(monkeypatch: pytest.MonkeyPatch):
    """A caller must be able to consume/persist each page as it arrives,
    not only after the whole (potentially very long, real-world-unbounded)
    walk finishes - proven here by consuming only the first item from the
    generator and confirming the second page was never even requested.
    """
    monkeypatch.setattr(cubecobra.time, "sleep", lambda *_: None)
    calls: list[dict[str, object]] = []

    def fake_post(url: str, json: dict[str, object], headers: dict[str, str], timeout: float) -> httpx.Response:
        calls.append(dict(json))
        page_num = len(calls)
        cube = {"id": f"cube-{page_num}", "shortId": f"slug-{page_num}", "name": f"Cube {page_num}"}
        return _search_response([cube], last_key={"PK": f"page-{page_num}"})

    monkeypatch.setattr(cubecobra.httpx, "post", fake_post)

    gen = cubecobra.iter_all_cubes("test-agent")
    first_page = next(gen)

    assert len(calls) == 1
    assert first_page[0].external_id == "cube-1"
