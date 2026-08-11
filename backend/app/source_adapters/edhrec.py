"""EDHREC synthesized-deck source — see SOURCE_ADAPTERS.md. EDHREC has no
public API and no hosted decklists to import (unlike moxfield.py/
archidekt.py) - it's a Next.js SSG site with real per-commander statistics
embedded in each page's `__NEXT_DATA__` JSON. This adapter scrapes that
(same technique used to discover Archidekt's real search API - see
archidekt.py) and synthesizes a decklist per commander from real average
deck-composition data, rather than fetching/parsing a decklist someone else
wrote. See app/models/edhrec.py for why this is a separate cache shape from
`PopularDeck`, and app/services/edhrec_service.py for the sync orchestration.
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from typing import Any

import httpx

from app.source_adapters.errors import SourceFetchError

COMMANDERS_URL = "https://edhrec.com/commanders"
COMMANDER_URL = "https://edhrec.com/commanders/{slug}"
COMMANDERS_LIST_TAG = "past2years"

# EDHREC has no lightweight search API - each commander needs a full page
# fetch (confirmed live: ~600-700KB HTML each). No 429 was seen firing 6
# rapid fetches during research, but a small delay between the many
# per-commander fetches a full sync makes keeps this respectful of EDHREC's
# servers, same reasoning as the Moxfield/Archidekt delay constants.
SYNTHESIS_REQUEST_DELAY_SECONDS = 0.5

_NEXT_DATA_RE = re.compile(
    r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', re.DOTALL
)

# EDHREC's cardlist `tag` values (found live) that map to one non-land
# category of our synthesized deck each - see `d[type]` count fields (also
# found live) for how many of each to actually pick.
_SIMPLE_CATEGORY_TAGS = {
    "creature": "creatures",
    "instant": "instants",
    "sorcery": "sorceries",
    "enchantment": "enchantments",
    "planeswalker": "planeswalkers",
    "battle": "battles",
}
_ARTIFACT_TAGS = ("manaartifacts", "utilityartifacts")
_LANDS_TAG = "lands"

_BASIC_LAND_BY_COLOR = {"W": "Plains", "U": "Island", "B": "Swamp", "R": "Mountain", "G": "Forest"}
_BASIC_LAND_NAMES = set(_BASIC_LAND_BY_COLOR.values())


@dataclass(frozen=True)
class CommanderRef:
    slug: str
    name: str
    rank: int
    num_decks: int


@dataclass(frozen=True)
class SynthesizedDeckEntry:
    commander_slug: str
    commander_name: str
    rank: int
    num_decks: int
    color_identity: list[str]
    card_count: int
    deck_text: str
    source_url: str


def _fetch_next_data(url: str, user_agent: str) -> dict[str, Any]:
    resp = httpx.get(url, headers={"User-Agent": user_agent}, timeout=30, follow_redirects=True)
    if resp.status_code != 200:
        raise SourceFetchError(f"EDHREC returned HTTP {resp.status_code} for {url}")
    match = _NEXT_DATA_RE.search(resp.text)
    if not match:
        raise SourceFetchError(f"EDHREC page at {url} has no __NEXT_DATA__ block - page shape may have changed")
    try:
        data: dict[str, Any] = json.loads(match.group(1))
    except json.JSONDecodeError as exc:
        raise SourceFetchError(f"EDHREC page at {url} has malformed __NEXT_DATA__ JSON") from exc
    return data


def fetch_popular_commanders(user_agent: str, *, limit: int = 100) -> list[CommanderRef]:
    """Real popularity ranking, not a curated list - EDHREC's own "Past 2
    Years" commander leaderboard (confirmed live: 100 entries, ranked by
    real `num_decks`).
    """
    data = _fetch_next_data(COMMANDERS_URL, user_agent)
    try:
        cardlists = data["props"]["pageProps"]["data"]["container"]["json_dict"]["cardlists"]
    except (KeyError, TypeError) as exc:
        raise SourceFetchError("EDHREC /commanders page JSON shape has changed - no cardlists found") from exc

    cardviews: list[dict[str, Any]] = []
    for cardlist in cardlists:
        if cardlist.get("tag") == COMMANDERS_LIST_TAG:
            cardviews = cardlist.get("cardviews") or []
            break
    if not cardviews:
        raise SourceFetchError(f"EDHREC /commanders page has no '{COMMANDERS_LIST_TAG}' cardlist")

    refs = []
    for cv in cardviews[:limit]:
        slug = cv.get("sanitized") or cv.get("slug")
        if not slug:
            continue
        refs.append(
            CommanderRef(slug=slug, name=cv.get("name") or slug, rank=cv.get("rank") or 0, num_decks=cv.get("num_decks") or 0)
        )
    return refs


def _pick_top(cardviews: list[dict[str, Any]], count: int, *, exclude_names: set[str] | None = None) -> list[str]:
    exclude = exclude_names or set()
    names: list[str] = []
    seen: set[str] = set()
    for cv in cardviews:
        name = cv.get("name")
        if not name or name in seen or name in exclude:
            continue
        seen.add(name)
        names.append(name)
        if len(names) >= count:
            break
    return names


def _synthesize_basics(color_identity: list[str], basic_count: int) -> list[str]:
    colors = [c for c in ("W", "U", "B", "R", "G") if c in color_identity]
    if not colors or basic_count <= 0:
        return []
    per_color, remainder = divmod(basic_count, len(colors))
    picks: list[str] = []
    for i, color in enumerate(colors):
        copies = per_color + (1 if i < remainder else 0)
        picks.extend([_BASIC_LAND_BY_COLOR[color]] * copies)
    return picks


def fetch_and_synthesize(commander: CommanderRef, user_agent: str) -> SynthesizedDeckEntry:
    """Fetches one commander's real EDHREC page and builds a decklist from
    its real average composition (`d[type]` counts) and real per-category
    play-rate rankings (`cardlists`) - see module docstring. Cards are
    picked most-played-first (`num_decks` descending, EDHREC's own default
    order), not randomly or alphabetically.
    """
    url = COMMANDER_URL.format(slug=commander.slug)
    data = _fetch_next_data(url, user_agent)
    try:
        page_data = data["props"]["pageProps"]["data"]
        json_dict = page_data["container"]["json_dict"]
        card = json_dict["card"]
        cardlists = json_dict["cardlists"]
    except (KeyError, TypeError) as exc:
        raise SourceFetchError(f"EDHREC commander page at {url} has an unexpected JSON shape") from exc

    color_identity = [c for c in card.get("color_identity") or [] if c in _BASIC_LAND_BY_COLOR]
    by_tag: dict[str, list[dict[str, Any]]] = {cl.get("tag"): cl.get("cardviews") or [] for cl in cardlists}

    lines: list[str] = [f"Commander: {commander.name}"]
    total = 0

    for type_field, tag in _SIMPLE_CATEGORY_TAGS.items():
        target = page_data.get(type_field) or 0
        if target <= 0:
            continue
        picks = _pick_top(by_tag.get(tag, []), target)
        lines.extend(picks)
        total += len(picks)

    artifact_target = page_data.get("artifact") or 0
    if artifact_target > 0:
        artifact_pool = [cv for tag in _ARTIFACT_TAGS for cv in by_tag.get(tag, [])]
        artifact_pool.sort(key=lambda cv: cv.get("num_decks") or 0, reverse=True)
        picks = _pick_top(artifact_pool, artifact_target)
        lines.extend(picks)
        total += len(picks)

    nonbasic_target = page_data.get("nonbasic") or 0
    if nonbasic_target > 0:
        picks = _pick_top(by_tag.get(_LANDS_TAG, []), nonbasic_target, exclude_names=_BASIC_LAND_NAMES)
        lines.extend(picks)
        total += len(picks)

    basic_target = page_data.get("basic") or 0
    basics = _synthesize_basics(color_identity, basic_target)
    lines.extend(basics)
    total += len(basics)

    return SynthesizedDeckEntry(
        commander_slug=commander.slug,
        commander_name=commander.name,
        rank=commander.rank,
        num_decks=commander.num_decks,
        color_identity=color_identity,
        card_count=total,
        deck_text="\n".join(lines),
        source_url=url,
    )


def fetch_and_synthesize_all(
    commanders: list[CommanderRef], user_agent: str
) -> tuple[list[SynthesizedDeckEntry], list[str]]:
    """Fetches+synthesizes every commander given, pacing requests. One
    commander's page failing doesn't abort the rest - a transient fetch
    error for one of a hundred pages shouldn't lose the other ninety-nine
    (same "no fake success, but no all-or-nothing either" reasoning as
    app.services.discover_service.run_discovery_sync's per-source handling).
    Returns (successful entries, error messages for the ones that failed).
    """
    entries: list[SynthesizedDeckEntry] = []
    errors: list[str] = []
    for i, commander in enumerate(commanders):
        if i > 0:
            time.sleep(SYNTHESIS_REQUEST_DELAY_SECONDS)
        try:
            entries.append(fetch_and_synthesize(commander, user_agent))
        except SourceFetchError as exc:
            errors.append(f"{commander.slug}: {exc}")
    return entries, errors
