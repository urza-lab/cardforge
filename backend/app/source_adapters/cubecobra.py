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
from dataclasses import dataclass
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
    """
    reader = csv.DictReader(io.StringIO(csv_text))
    fieldnames = list(reader.fieldnames or []) + ["Quantity"]
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=fieldnames)
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


def fetch_popular_cubes(user_agent: str, *, pages: int = POPULAR_CUBES_PAGES) -> list[PopularCubeEntry]:
    """Real public data from CubeCobra's own search, sorted by real like
    count - see module docstring for the endpoint. Paginated via lastKey
    (a DynamoDB cursor, not a page number), so this must walk pages in
    order rather than fetching them independently.
    """
    headers = {"User-Agent": user_agent, "Content-Type": "application/json", "Accept": "application/json"}
    entries: list[PopularCubeEntry] = []
    last_key: object | None = None

    for page in range(pages):
        if page > 0:
            time.sleep(POPULAR_CUBES_REQUEST_DELAY_SECONDS)

        resp = httpx.post(
            SEARCH_ENDPOINT,
            json={"lastKey": last_key, "query": "", "order": "pop", "ascending": False},
            headers=headers,
            timeout=30,
        )
        if resp.status_code != 200:
            raise SourceFetchError(f"CubeCobra popular-cubes search returned HTTP {resp.status_code} (page={page})")

        data = resp.json()
        cubes = data.get("cubes") or []
        if not cubes:
            break

        for c in cubes:
            cube_id = c.get("id")
            if not cube_id:
                continue
            short_id = c.get("shortId") or cube_id
            entries.append(
                PopularCubeEntry(
                    external_id=str(cube_id),
                    short_id=str(short_id),
                    name=c.get("name") or "(untitled)",
                    owner_username=(c.get("owner") or {}).get("username"),
                    source_url=f"https://cubecobra.com/cube/list/{short_id}",
                    card_count=c.get("cardCount") or 0,
                    like_count=c.get("likeCount") or 0,
                    tags=c.get("tags") or None,
                )
            )

        last_key = data.get("lastKey")
        if not last_key:
            break

    return entries
