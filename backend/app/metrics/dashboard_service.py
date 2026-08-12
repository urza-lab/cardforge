"""Native dashboard aggregate queries (Phase 7) — see ARCHITECTURE.md
"metrics/ Dashboard aggregate queries + Prometheus exporters". Pulls
together numbers that already live in other services/tables (collection
size, sync state, list buildability) plus the collection-leverage ranking
(`app.comparison.leverage`) into one response the frontend's Dashboard page
renders in a single request, rather than the page firing half a dozen
separate calls itself.
"""
from __future__ import annotations

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
from app.models.pricing import PriceProvider, PriceSyncState
from app.models.scryfall import SYNC_STATE_ID, ScryfallSyncState
from app.models.user import DEFAULT_USER_ID
from app.services import collection_service, pricing_service
from app.services.comparison_service import _owned_cards, required_cards_by_list

# The leverage computation itself (app.comparison.leverage) doesn't get any
# more expensive by returning more of its already-computed candidates - the
# full ranking is computed regardless, this just controls how much of it is
# exposed. Bumped from an original 10 (enough for a fixed top-N display) to
# 100 once the frontend gained client-side filtering (by min lists-newly-
# buildable, max price) - user-requested, since filtering only 10 candidates
# wasn't useful.
TOP_LEVERAGE_COUNT = 100

# Basic lands are never a real purchasing decision (unlimited supply, not
# actually scarce) - user-requested exclusion from "what to buy next" after
# real data showed them dominating the ranking. Their raw numbers are
# wildly inflated purely by how many copies real decks/cubes want in
# aggregate (thousands, summed across hundreds of lists - confirmed live:
# "buy 3094 Mountains" outranking single-copy, one-deck-completing cards
# by coverage-gain alone), crowding out genuinely actionable signals with
# advice nobody would act on. Filtered by exact (case-insensitive) name,
# not oracle_id, since this list also includes ad-hoc/unresolved entries.
_BASIC_LAND_NAMES = {
    "plains", "island", "swamp", "mountain", "forest", "wastes",
    "snow-covered plains", "snow-covered island", "snow-covered swamp",
    "snow-covered mountain", "snow-covered forest", "snow-covered wastes",
}

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
class PricedLeverageCandidate:
    """`LeverageCandidate` (app.comparison.leverage - a pure, DB/pricing-
    free library, see ARCHITECTURE.md) plus real market price, added here
    rather than on that dataclass itself so leverage.py stays pricing-
    oblivious. `unit_price`/`total_price`/`currency` are None when no
    price resolved for this card at all - shown as such in the UI (no fake
    success), not silently omitted, since a human filtering this list by
    price needs to know a candidate exists even if its price is unknown.
    """

    name: str
    oracle_id: str | None
    scryfall_card_id: str | None
    quantity_needed: int
    lists_newly_buildable: int
    total_coverage_gain: float
    unit_price: Decimal | None
    total_price: Decimal | None
    currency: str | None


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
    top_leverage: list[PricedLeverageCandidate] = field(default_factory=list)


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
    price_by_oracle, price_by_direct = pricing_service.batch_cheapest_prices(db, oracle_ids, direct_card_ids, profile)

    def price_for(missing: MissingCard) -> Decimal | None:
        if missing.oracle_id:
            return price_by_oracle.get(missing.oracle_id)
        if missing.scryfall_card_id:
            return price_by_direct.get(missing.scryfall_card_id)
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


def price_leverage_candidates(
    db: Session, candidates: list[LeverageCandidate], *, user_id: int = DEFAULT_USER_ID
) -> list[PricedLeverageCandidate]:
    """Real market price per candidate (user-requested, so the "what to buy
    next" table can be filtered by price, not just browsed as a fixed top-
    10) - reuses the same batched, chunked lookup `compute_list_missing_cost`
    uses (`pricing_service.batch_cheapest_prices`), not a per-candidate DB
    round-trip, for the same reason: this can be dozens to hundreds of
    candidates, not one.
    """
    profile = pricing_service.get_or_create_default_price_profile(db, user_id=user_id)
    oracle_ids = {c.oracle_id for c in candidates if c.oracle_id}
    direct_card_ids = {c.scryfall_card_id for c in candidates if not c.oracle_id and c.scryfall_card_id}
    price_by_oracle, price_by_direct = pricing_service.batch_cheapest_prices(db, oracle_ids, direct_card_ids, profile)

    priced: list[PricedLeverageCandidate] = []
    for c in candidates:
        unit_price = price_by_oracle.get(c.oracle_id) if c.oracle_id else None
        if unit_price is None and c.scryfall_card_id:
            unit_price = price_by_direct.get(c.scryfall_card_id)
        total_price = unit_price * c.quantity_needed if unit_price is not None else None
        priced.append(
            PricedLeverageCandidate(
                name=c.name,
                oracle_id=c.oracle_id,
                scryfall_card_id=c.scryfall_card_id,
                quantity_needed=c.quantity_needed,
                lists_newly_buildable=c.lists_newly_buildable,
                total_coverage_gain=c.total_coverage_gain,
                unit_price=unit_price,
                total_price=total_price,
                currency=profile.currency if unit_price is not None else None,
            )
        )
    return priced


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
    leverage_candidates = [
        c for c in compute_leverage(owned, lists_required, settings) if c.name.strip().lower() not in _BASIC_LAND_NAMES
    ]
    top_leverage = price_leverage_candidates(db, leverage_candidates[:TOP_LEVERAGE_COUNT], user_id=user_id)

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
