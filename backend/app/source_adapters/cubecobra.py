"""CubeCobra public cube import — see SOURCE_ADAPTERS.md. CubeCobra has no
documented public API, but is open source (github.com/dekkerglen/CubeCobra);
its real routes were found by reading the actual server source, the same
technique that found Archidekt's real search API and confirmed EDHREC's real
page-data shape. Two real endpoints, both live-verified, no login needed:

- `POST /search/getmoresearchitems` (packages/server/src/router/routes/
  search.ts) - real cube search, `order: "pop"` sorts by real like count,
  paginated via a DynamoDB `lastKey` cursor (36 cubes/page) rather than page
  numbers.
- `GET /cube/download/csv/{id}` (packages/server/src/router/routes/cube/
  download.ts) - a real CSV export of one cube's actual mainboard card
  list. Accepts either a cube's real id or its human-friendly shortId
  (confirmed live: both `.../csv/5d2cb3f44153591614458e5d` and
  `.../csv/modovintage` return the same real MODO Vintage Cube list) -
  matches the same `/cube/list/{id-or-shortId}` URL CubeCobra's own site
  links to, so either form works as an import URL here too.
"""
from __future__ import annotations

import csv
import io
import time
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse

import httpx

from app.parsers.common import ParseResult
from app.parsers.list_csv import parse_list_csv
from app.security.ssrf_guard import AuthRequiredError, guarded_get
from app.source_adapters.common import DeckFetchResult
from app.source_adapters.errors import InvalidUrlError, SourceFetchError

SOURCE_NAME = "cubecobra"
SEARCH_ENDPOINT = "https://cubecobra.com/search/getmoresearchitems"
CSV_ENDPOINT = "https://cubecobra.com/cube/download/csv"

# Each page is a fixed 36 cubes (CubeCobra's own page size, not configurable)
# fetched via lastKey cursor pagination - 40 pages ~= 1,440 cubes, comparable
# in scale to the Moxfield/Archidekt deck pools. No rate-limiting observed
# during research, but a small delay keeps this respectful regardless, same
# reasoning as the deck adapters' own delay constants.
POPULAR_CUBES_PAGES = 40
POPULAR_CUBES_REQUEST_DELAY_SECONDS = 0.5

# A real full-catalog scrape (app.services.cube_discover_service.
# run_full_cube_scrape) makes thousands of sequential requests over several
# hours - confirmed live to hit a real, transient SSL handshake timeout
# twice in separate multi-hour runs, both around the ~3.3-3.5h/~7,000-page
# mark (see CLAUDE.md). A single transient network hiccup that deep into a
# multi-hour job shouldn't abort everything after it - retry the one
# failing request with a short backoff before giving up, same "don't let
# one bad thing sink the whole batch" principle as gotcha #34's row-level
# truncation fix, just at the request level instead of the row level.
POPULAR_CUBES_MAX_RETRIES = 3
POPULAR_CUBES_RETRY_BACKOFF_SECONDS = 5.0

# CubeCobra's real CSV export header names (confirmed live) mapped onto our
# canonical CardListItem fields - passed as an explicit column_mapping to
# app.parsers.list_csv.parse_list_csv rather than relying on its own header-
# alias auto-detection, since "Set" would otherwise auto-match `set_name`
# (its alias list includes the bare word "set") when the column actually
# holds a short set *code* like "mh3", not a full set name.
_CSV_COLUMN_MAPPING = {
    "name": "name",
    "set_code": "Set",
    "collector_number": "Collector Number",
    "quantity": "Quantity",  # synthetic - see _inject_quantity_column below, cubes have no quantity column
    "foil": "Finish",
    "section": "board",
    "tags": "tags",
}


@dataclass(frozen=True)
class PopularCubeEntry:
    external_id: str
    short_id: str
    name: str
    owner_username: str | None
    source_url: str
    card_count: int
    like_count: int
    tags: list[str] | None
    # Real quality/popularity signals beyond likeCount, user-requested after
    # checking what CubeCobra's own search response actually exposes (no
    # comment count or star rating exists in that payload - confirmed live,
    # see CLAUDE.md): numDecks is how many real decks have been built from
    # this cube (the same "num_decks" concept EDHREC's own real per-
    # commander stats use), dateLastUpdated is when the cube's owner last
    # edited it on CubeCobra itself.
    num_decks: int | None
    date_last_updated: datetime | None


def validate_url(url: str) -> bool:
    try:
        extract_cube_id(url)
    except InvalidUrlError:
        return False
    return True


def extract_cube_id(url: str) -> str:
    parsed = urlparse(url)
    if parsed.hostname not in {"cubecobra.com", "www.cubecobra.com"}:
        raise InvalidUrlError(f"'{url}' is not a cubecobra.com URL")
    parts = [p for p in parsed.path.split("/") if p]
    # Every real cube page (`/cube/list/<id>`, `/cube/overview/<id>`, ...)
    # ends in the cube's id/shortId - taking the last segment is robust to
    # whichever specific page URL a user pastes, not just the one this
    # adapter itself generates for cached PopularCube rows.
    if len(parts) < 2 or parts[0] != "cube":
        raise InvalidUrlError(f"'{url}' doesn't look like a CubeCobra cube URL (expected /cube/.../<id>)")
    return parts[-1]


def _inject_quantity_column(csv_text: str) -> str:
    """CubeCobra's CSV has no quantity column at all - cubes are singleton
    by definition, every card just 1 copy. app.parsers.list_csv.parse_list_csv
    hard-requires a detected quantity column for any CSV source, so one is
    added here (adapter-local pre-processing) rather than changing that
    shared parser's behavior for every other CSV caller.

    `extrasaction="ignore"` on the writer: a real CubeCobra export can have
    a malformed row (confirmed live - a free-text "Notes" cell with an
    unescaped quote character shifts every later column on that one row),
    which makes `csv.DictReader` stash the overflow under a `None` key.
    `csv.DictWriter` raises on an unrecognized key by default, which was
    aborting the *entire* cube's import over a single bad row - even
    though every field this adapter actually maps (name/Set/Collector
    Number/Finish/board/tags, see `_CSV_COLUMN_MAPPING`) sits earlier in
    the row than where CubeCobra's export breaks, so silently dropping the
    unrecognized overflow doesn't lose anything this adapter uses.
    """
    reader = csv.DictReader(io.StringIO(csv_text))
    fieldnames = list(reader.fieldnames or []) + ["Quantity"]
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=fieldnames, extrasaction="ignore")
    writer.writeheader()
    for row in reader:
        row["Quantity"] = "1"
        writer.writerow(row)
    return out.getvalue()


def fetch_and_parse(url: str, user_agent: str) -> DeckFetchResult:
    cube_id = extract_cube_id(url)
    resp = guarded_get(f"{CSV_ENDPOINT}/{cube_id}", headers={"User-Agent": user_agent, "Accept": "text/plain"})

    if resp.status_code in (401, 403):
        raise AuthRequiredError(f"CubeCobra cube '{cube_id}' requires login (private or restricted)")
    if resp.status_code == 404:
        raise SourceFetchError(f"CubeCobra cube '{cube_id}' not found")
    if resp.status_code != 200:
        raise SourceFetchError(f"CubeCobra returned HTTP {resp.status_code} for cube '{cube_id}'")

    # A private/nonexistent cube redirects to a normal 200 HTML error page
    # rather than a 404 (confirmed live) - the real CSV always starts with
    # this exact header row, so anything else means "not a real export".
    if not resp.text.startswith("name,CMC,Type,Color,Set,"):
        raise SourceFetchError(f"CubeCobra cube '{cube_id}' did not return a real CSV export (private or removed?)")

    try:
        parse_result: ParseResult = parse_list_csv(_inject_quantity_column(resp.text), column_mapping=_CSV_COLUMN_MAPPING)
    except Exception as exc:  # noqa: BLE001 - a malformed export must surface as a normal fetch failure, not a 500
        raise SourceFetchError(f"CubeCobra cube '{cube_id}' CSV could not be parsed: {exc}") from exc

    return DeckFetchResult(deck_name=None, parse_result=parse_result)


def attribution(cube_url: str) -> str:
    return f"Imported from CubeCobra: {cube_url}"


def _map_cube_entry(c: dict[str, Any]) -> PopularCubeEntry | None:
    cube_id = c.get("id")
    if not cube_id:
        return None
    short_id = c.get("shortId") or cube_id
    date_last_updated_ms = c.get("dateLastUpdated")
    return PopularCubeEntry(
        external_id=str(cube_id),
        short_id=str(short_id),
        name=c.get("name") or "(untitled)",
        owner_username=(c.get("owner") or {}).get("username"),
        source_url=f"https://cubecobra.com/cube/list/{short_id}",
        card_count=c.get("cardCount") or 0,
        like_count=c.get("likeCount") or 0,
        tags=c.get("tags") or None,
        num_decks=c.get("numDecks"),
        date_last_updated=(
            datetime.fromtimestamp(date_last_updated_ms / 1000, tz=UTC) if date_last_updated_ms else None
        ),
    )


def _post_with_retry(url: str, *, json: dict[str, Any], headers: dict[str, str], page_num: int) -> httpx.Response:
    """Retries a single page request on a transient transport-level error
    (connection reset, SSL handshake timeout, read timeout, etc.) - not on
    a real HTTP error status, which the caller handles itself (a 429/5xx is
    data about the request, not evidence the request never happened, so
    retrying it here isn't the right layer for that). See
    POPULAR_CUBES_MAX_RETRIES's own comment for why this exists.
    """
    last_exc: httpx.TransportError | None = None
    for attempt in range(POPULAR_CUBES_MAX_RETRIES + 1):
        try:
            return httpx.post(url, json=json, headers=headers, timeout=30)
        except httpx.TransportError as exc:
            last_exc = exc
            if attempt < POPULAR_CUBES_MAX_RETRIES:
                time.sleep(POPULAR_CUBES_RETRY_BACKOFF_SECONDS)
    raise SourceFetchError(
        f"CubeCobra cube search failed after {POPULAR_CUBES_MAX_RETRIES + 1} attempts (page={page_num}): {last_exc}"
    ) from last_exc


def fetch_popular_cubes(user_agent: str, *, pages: int = POPULAR_CUBES_PAGES) -> list[PopularCubeEntry]:
    """Real public data from CubeCobra's own search, sorted by real like
    count - see module docstring for the endpoint. Paginated via lastKey
    (a DynamoDB cursor, not a page number), so this must walk pages in
    order rather than fetching them independently.
    """
    entries: list[PopularCubeEntry] = []
    for page, _last_key in iter_all_cubes(user_agent, max_pages=pages):
        entries.extend(page)
    return entries


def iter_all_cubes(
    user_agent: str, *, max_pages: int | None = None, start_key: object | None = None
) -> Iterator[tuple[list[PopularCubeEntry], object | None]]:
    """Walks CubeCobra's real search API to genuine exhaustion (until its
    `lastKey` cursor runs out), not stopping at a fixed page count like
    `fetch_popular_cubes` does - user-requested full-catalog scrape, since
    "browse by popularity, N pages deep" can structurally never reach an
    obscure/unliked cube no matter how deep N is (confirmed live against a
    real 0-like, 0-deck cube a user linked - see CLAUDE.md). `max_pages`
    exists only so `fetch_popular_cubes` above can reuse this same walk
    logic with its existing bound; the real full-scrape caller leaves it
    unset. `start_key` resumes a previous walk from exactly where it left
    off (user-requested/found live: without this, retrying a failed multi-
    hour scrape always restarted from page 1, real network requests
    included, re-covering already-known ground before ever reaching new
    territory - safe, since upserts never duplicate, but a real waste of
    hours) - `None` (the default) starts a fresh walk from the beginning.

    A generator, not a function returning the full list, so a caller
    (cube_discover_service.run_full_cube_scrape) can persist progress
    incrementally instead of only at the end - there is no way to know the
    real total cube count in advance (CubeCobra exposes no count endpoint),
    so this can run for an unknown, potentially very long time, and a
    worker restart or crash partway through should lose at most the
    in-flight page, not everything found so far. Yields `(page, last_key)`
    pairs - `last_key` is CubeCobra's own cursor *after* this page, i.e.
    exactly what a caller should persist and later pass back as `start_key`
    to resume from here; `None` means the walk reached genuine exhaustion
    on this same page.
    """
    headers = {"User-Agent": user_agent, "Content-Type": "application/json", "Accept": "application/json"}
    last_key: object | None = start_key
    page_num = 0

    while max_pages is None or page_num < max_pages:
        if page_num > 0:
            time.sleep(POPULAR_CUBES_REQUEST_DELAY_SECONDS)

        resp = _post_with_retry(
            SEARCH_ENDPOINT,
            json={"lastKey": last_key, "query": "", "order": "pop", "ascending": False},
            headers=headers,
            page_num=page_num,
        )
        if resp.status_code != 200:
            raise SourceFetchError(f"CubeCobra cube search returned HTTP {resp.status_code} (page={page_num})")

        data = resp.json()
        cubes_raw = data.get("cubes") or []
        if not cubes_raw:
            return

        page = [entry for c in cubes_raw if (entry := _map_cube_entry(c)) is not None]
        last_key = data.get("lastKey")
        yield page, last_key

        page_num += 1
        if not last_key:
            return
