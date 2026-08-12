"""Native dashboard aggregate queries (Phase 7) — see ARCHITECTURE.md
"metrics/ Dashboard aggregate queries + Prometheus exporters". Pulls
together numbers that already live in other services/tables (collection
size, sync state, list buildability) plus the collection-leverage ranking
(`app.comparison.leverage`) into one response the frontend's Dashboard page
renders in a single request, rather than the page firing half a dozen
separate calls itself.
"""
from __future__ import annotations

from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.comparison import ComparisonSettings, LeverageCandidate, compute_leverage
from app.comparison.engine import build_owned_pool, compare_pool
from app.comparison.types import MissingCard, RequiredCard
from app.models.collection import CollectionItem
from app.models.lists import CardList
from app.models.pricing import PriceObservation, PriceProvider, PriceSyncState
from app.models.scryfall import SYNC_STATE_ID, ScryfallCard, ScryfallSyncState
from app.models.user import DEFAULT_USER_ID
from app.services import collection_service, pricing_service
from app.services.comparison_service import _owned_cards, required_cards_by_list

# Capped so a household with dozens of decks/cubes doesn't turn every
# dashboard load into an O(candidates x lists) leverage computation over
# an unbounded candidate set - see app.comparison.leverage's own note on
# not being batched. 10 is enough to answer "what should I buy next", not
# meant as an exhaustive report.
TOP_LEVERAGE_COUNT = 10

# Postgres hard-caps a single query at 65535 bound parameters - an IN(...)
# clause built from a real, large card-id set (hundreds of lists' worth of
# missing cards, confirmed live to reach tens of thousands of distinct ids,
# see CLAUDE.md) can exceed that and fail the query outright, not just run
# slowly. Chunking well under the ceiling keeps every batch safe regardless
# of how large the real set grows.
_IN_CLAUSE_CHUNK_SIZE = 5000


def _chunked(items: Iterable[str], size: int = _IN_CLAUSE_CHUNK_SIZE) -> Iterator[list[str]]:
    chunk: list[str] = []
    for item in items:
        chunk.append(item)
        if len(chunk) >= size:
            yield chunk
            chunk = []
    if chunk:
        yield chunk


@dataclass(frozen=True)
class ListBuildability:
    list_id: int
    name: str
    list_type: str
    coverage_percent: float
    is_fully_buildable: bool
    # In-memory only - not part of ListBuildabilityRead (app/schemas/dashboard.py
    # whitelists fields explicitly), kept here so compute_list_missing_cost
    # below doesn't need to re-run compare() from scratch for the same list.
    missing: list[MissingCard] = field(default_factory=list, repr=False, compare=False)


@dataclass(frozen=True)
class ListMissingCost:
    list_id: int
    name: str
    list_type: str
    total_cost: Decimal
    currency: str


@dataclass(frozen=True)
class DashboardSummary:
    collection_distinct_items: int
    collection_total_quantity: int
    collection_resolved_count: int
    list_count: int
    lists_fully_buildable: int
    average_coverage_percent: float
    scryfall_sync_status: str
    scryfall_card_count: int
    scryfall_source_updated_at: datetime | None
    mtgjson_sync_status: str
    mtgjson_price_count: int
    list_buildability: list[ListBuildability] = field(default_factory=list)
    top_leverage: list[LeverageCandidate] = field(default_factory=list)


def compute_list_buildability(
    db: Session, *, user_id: int = DEFAULT_USER_ID
) -> tuple[list[ListBuildability], dict[int, list[RequiredCard]]]:
    """Split out of `get_dashboard_summary` so callers that only need
    per-list coverage (the Prometheus exporter) don't also pay for the
    leverage computation below, which is meaningfully more expensive
    (O(candidates x lists), see `app.comparison.leverage`) and would
    otherwise run on every Prometheus scrape for no reason.
    """
    collection = collection_service.get_or_create_default_collection(db, user_id=user_id)
    lists = list(db.scalars(select(CardList).where(CardList.user_id == user_id)))
    owned = _owned_cards(db, collection.id)
    settings = ComparisonSettings(mode="oracle")
    # Built once and reused read-only across every list's compare_pool()
    # call below (see engine.build_owned_pool/compare_pool's own
    # docstrings) - compare()'s own per-call pool rebuild is the dominant
    # cost once there are hundreds of lists, not the comparison itself.
    owned_pool = build_owned_pool(owned, settings.mode)

    lists_required = required_cards_by_list(db, [card_list.id for card_list in lists])

    list_buildability: list[ListBuildability] = []
    for card_list in lists:
        required = lists_required[card_list.id]
        result = compare_pool(owned_pool, required, settings)
        list_buildability.append(
            ListBuildability(
                list_id=card_list.id,
                name=card_list.name,
                list_type=card_list.list_type,
                coverage_percent=result.coverage_percent,
                is_fully_buildable=result.is_fully_buildable,
                missing=result.missing,
            )
        )
    return list_buildability, lists_required


def compute_list_missing_cost(
    db: Session, list_buildability: list[ListBuildability], *, user_id: int = DEFAULT_USER_ID
) -> list[ListMissingCost]:
    """Total cost to complete each list (sum of missing-card prices), using
    the user's default price profile - real market prices only (Scryfall/
    MTGJSON sync, see PRICING.md), never estimated. A list is only included
    if *every* one of its missing cards actually resolved a price - "no fake
    success": a partial total that silently excludes unpriced cards would
    understate the real cost, so it's omitted entirely rather than shown as
    a misleadingly low number.

    Deliberately NOT built on pricing_service.price_missing_cards/
    resolve_cheapest_price_for_oracle - those do one (or several) DB
    round-trips per missing card, which is fine for their actual callers (a
    single list's own comparison page, on demand) but was confirmed live to
    take minutes across a real collection's real decks when run for every
    list on every call here - this is reached from the Prometheus exporter,
    scraped on a timer, so it needs to stay a small constant number of
    queries regardless of how many cards are missing across how many lists.
    """
    profile = pricing_service.get_or_create_default_price_profile(db, user_id=user_id)

    oracle_ids = {m.oracle_id for lb in list_buildability for m in lb.missing if m.oracle_id}
    direct_card_ids = {
        m.scryfall_card_id for lb in list_buildability for m in lb.missing if not m.oracle_id and m.scryfall_card_id
    }

    # oracle_id -> every *priced* printing's scryfall_card_id (oracle-mode
    # pricing takes the cheapest printing, same "any printing satisfies
    # this" philosophy as oracle-mode comparison itself). A single JOINed
    # query per oracle_id chunk, filtered to this profile's currency/foil
    # up front, rather than first fetching *every* printing of every
    # candidate oracle_id (confirmed live to reach 400k+ rows for ~24k
    # oracle_ids - most of the real Scryfall mirror - see CLAUDE.md) and
    # only then discovering which of those even have a price. Real decks/
    # cubes only have prices for a fraction of all printings, so this join
    # touches far fewer rows in practice.
    printings_by_oracle: dict[str, list[str]] = {}
    price_by_card_provider: dict[tuple[str, str], Decimal] = {}
    for chunk in _chunked(oracle_ids):
        for oracle_id, card_id, provider, price in db.execute(
            select(ScryfallCard.oracle_id, PriceObservation.scryfall_card_id, PriceObservation.provider, PriceObservation.price)
            .join(PriceObservation, PriceObservation.scryfall_card_id == ScryfallCard.id)
            .where(
                ScryfallCard.oracle_id.in_(chunk),
                PriceObservation.currency == profile.currency,
                PriceObservation.foil == profile.prefer_foil,
            )
        ):
            printings_by_oracle.setdefault(oracle_id, []).append(card_id)
            price_by_card_provider[(card_id, provider)] = price

    for chunk in _chunked(direct_card_ids):
        for card_id, provider, price in db.execute(
            select(PriceObservation.scryfall_card_id, PriceObservation.provider, PriceObservation.price).where(
                PriceObservation.scryfall_card_id.in_(chunk),
                PriceObservation.currency == profile.currency,
                PriceObservation.foil == profile.prefer_foil,
            )
        ):
            price_by_card_provider[(card_id, provider)] = price

    def cheapest_price(card_ids: list[str]) -> Decimal | None:
        best: Decimal | None = None
        for card_id in card_ids:
            for provider in profile.provider_priority:
                price = price_by_card_provider.get((card_id, provider))
                if price is not None:
                    if best is None or price < best:
                        best = price
                    break  # this printing's cheapest-available-provider price is settled - move on
        return best

    # Precomputed once per distinct oracle_id/card_id, not once per missing
    # *line* - the same card can be missing from dozens of lists, and this
    # loop previously recomputed its cheapest price from scratch every
    # single time (confirmed live: ~255k missing lines across 590 real
    # lists, but only ~24k distinct oracle_ids among them - a ~10x
    # redundant-work factor, see CLAUDE.md).
    cheapest_by_oracle = {oracle_id: cheapest_price(ids) for oracle_id, ids in printings_by_oracle.items()}
    cheapest_by_card_id = {card_id: cheapest_price([card_id]) for card_id in direct_card_ids}

    def price_for(missing: MissingCard) -> Decimal | None:
        if missing.oracle_id:
            return cheapest_by_oracle.get(missing.oracle_id)
        if missing.scryfall_card_id:
            return cheapest_by_card_id.get(missing.scryfall_card_id)
        return None

    results: list[ListMissingCost] = []
    for lb in list_buildability:
        total = Decimal(0)
        fully_priced = True
        for m in lb.missing:
            price = price_for(m)
            if price is None:
                fully_priced = False
                break
            total += price * m.missing_quantity
        if fully_priced:
            results.append(
                ListMissingCost(list_id=lb.list_id, name=lb.name, list_type=lb.list_type, total_cost=total, currency=profile.currency)
            )

    return results


def get_dashboard_summary(db: Session, user_id: int = DEFAULT_USER_ID) -> DashboardSummary:
    collection = collection_service.get_or_create_default_collection(db, user_id=user_id)

    distinct_items, total_quantity, resolved_count = db.execute(
        select(
            func.count(CollectionItem.id),
            func.coalesce(func.sum(CollectionItem.quantity), 0),
            func.count(CollectionItem.id).filter(CollectionItem.resolved_oracle_id.is_not(None)),
        ).where(CollectionItem.collection_id == collection.id)
    ).one()

    owned = _owned_cards(db, collection.id)
    settings = ComparisonSettings(mode="oracle")
    list_buildability, lists_required = compute_list_buildability(db, user_id=user_id)

    lists_fully_buildable = sum(1 for lb in list_buildability if lb.is_fully_buildable)
    average_coverage = (
        round(sum(lb.coverage_percent for lb in list_buildability) / len(list_buildability), 2)
        if list_buildability
        else 0.0
    )
    top_leverage = compute_leverage(owned, lists_required, settings)[:TOP_LEVERAGE_COUNT]

    scryfall_state = db.get(ScryfallSyncState, SYNC_STATE_ID)
    mtgjson_state = db.get(PriceSyncState, PriceProvider.mtgjson.value)

    return DashboardSummary(
        collection_distinct_items=distinct_items,
        collection_total_quantity=int(total_quantity),
        collection_resolved_count=resolved_count,
        list_count=len(list_buildability),
        lists_fully_buildable=lists_fully_buildable,
        average_coverage_percent=average_coverage,
        scryfall_sync_status=scryfall_state.status if scryfall_state else "NOT_STARTED",
        scryfall_card_count=scryfall_state.card_count if scryfall_state else 0,
        scryfall_source_updated_at=scryfall_state.source_updated_at if scryfall_state else None,
        mtgjson_sync_status=mtgjson_state.status if mtgjson_state else "NOT_STARTED",
        mtgjson_price_count=mtgjson_state.price_count if mtgjson_state else 0,
        list_buildability=list_buildability,
        top_leverage=top_leverage,
    )
