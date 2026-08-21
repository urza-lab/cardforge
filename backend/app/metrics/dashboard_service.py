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

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.comparison import LeverageCandidate
from app.comparison.engine import build_owned_pool
from app.models.collection import CollectionItem
from app.models.lists import CardList
from app.models.pricing import PriceProvider, PriceSyncState
from app.models.scryfall import SYNC_STATE_ID, ScryfallSyncState
from app.models.user import DEFAULT_USER_ID
from app.services import collection_service, pricing_service
from app.services.comparison_service import REQUIRED_LIST_SECTIONS, _owned_cards

# Every query below groups card_list_items by this same expression - oracle_id
# when resolved, else a normalized-name fallback - to match exactly what
# `app.comparison.engine._oracle_key` groups on in the (still correct, still
# used for smaller inputs) pure-Python comparison engine. Written once here
# and interpolated into each query's `required` CTE rather than copy-pasted,
# so the three queries can never drift out of sync with each other or with
# `_oracle_key`.
_KEY_EXPR_SQL = (
    "COALESCE(cli.resolved_oracle_id, 'name::' || "
    "regexp_replace(trim(lower(cli.card_name)), '\\s+', ' ', 'g'))"
)

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
    # whitelists fields explicitly). No longer holds per-card missing detail
    # (an earlier version did, for compute_list_missing_cost/
    # compute_leverage_at_scale to reuse without re-querying - see CLAUDE.md
    # 2026-08-20: even a compact per-entry tuple representation still OOM'd a
    # 3GB container once retained for all ~84,000 lists at once, since a
    # bulk-imported cube the user never owned has "missing" almost as large
    # as "required". Those two functions now get everything they need from
    # their own SQL aggregations instead, so this dataclass only needs to
    # carry per-list *summary* numbers, not per-card detail.
    total_required_quantity: int = field(default=0, repr=False, compare=False)


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
    # Real cost-to-complete per list (user-requested "indicative first
    # guess" price column on the Decks & Cubes overview page) - the exact
    # same batched compute_list_missing_cost() the Prometheus exporter
    # already uses, just reused here so it rides the dashboard's own 60s
    # cache (app.metrics.dashboard_cache) instead of a fresh per-request
    # computation - "loads fast" was the explicit ask, and this is already
    # the fast path (near-instant once the cache is warm), not a new one.
    list_missing_cost: list[ListMissingCost] = field(default_factory=list)
    # Populated by app.metrics.dashboard_cache, not by get_dashboard_summary
    # itself (which always computes a genuinely fresh, real result) - see
    # that module for why a real ~14s computation at real data scale gets
    # served from a short-lived cache with an honest "still on the old
    # data, refreshing, ETA ~Xs" signal instead of either blocking every
    # request or silently going stale with no indication.
    computed_at: datetime | None = None
    is_refreshing: bool = False
    refresh_eta_seconds: float | None = None


# A real, live OOM (2026-08-19): once the collection passed 82,000 real
# lists (the full CubeCobra import completing), the old version of this
# function fetched *every* required-card row for *every* list into one
# giant Python dict before processing any of them (see gotcha history in
# CLAUDE.md) - tens of millions of RequiredCard objects held at once, which
# no longer fits even a raised 3GB container limit. Processing lists in
# bounded batches keeps the working set at any moment proportional to
# batch size, not total collection size, regardless of how large the real
# list count grows.
def _owned_pool_arrays(owned_pool: dict[str, int]) -> tuple[list[str], list[int]]:
    keys = list(owned_pool.keys())
    return keys, [owned_pool[k] for k in keys]


def compute_list_buildability(
    db: Session, *, user_id: int = DEFAULT_USER_ID
) -> list[ListBuildability]:
    """Split out of `get_dashboard_summary` so callers that only need
    per-list coverage (the Prometheus exporter) don't also pay for the
    leverage computation below, which is meaningfully more expensive
    (O(candidates x lists), see `app.comparison.leverage`) and would
    otherwise run on every Prometheus scrape for no reason.

    A real, live OOM (2026-08-19/20): once the collection passed 82,000
    real lists (the full CubeCobra import completing), the old version of
    this function - and `compute_leverage_at_scale`/`compute_list_missing_
    cost` below - worked by fetching every required-card row into Python
    RequiredCard/MissingCard objects (or even a leaner compact tuple form)
    and iterating them in `app.comparison.engine.compare_pool`. That
    doesn't scale to a real ~37 million-row `card_list_items` table no
    matter how lean the per-row Python representation gets: a bulk-
    imported cube the user never owned has "missing" almost as large as
    "required", so the *retained* per-list output alone was enough to OOM
    a 3GB container. This version pushes the entire aggregation into one
    SQL query instead - Postgres processes the 37M rows internally (no
    per-row Python object ever created) and only ships back one row per
    *list* (bounded by list count, not row count).

    Mathematically equivalent to the old per-row compare_pool() loop, not
    an approximation of it: `compare_pool` only ever depends on the *sum*
    of required quantities per candidate key against the owned pool
    (`applied = min(available, quantity)` against a running total), never
    on how that sum was split across individual required-card lines - see
    `_KEY_EXPR_SQL`'s own note on matching `app.comparison.engine.
    _oracle_key`'s exact grouping.
    """
    collection = collection_service.get_or_create_default_collection(db, user_id=user_id)
    lists = list(db.scalars(select(CardList).where(CardList.user_id == user_id)))
    owned = _owned_cards(db, collection.id)
    owned_pool = build_owned_pool(owned, "oracle")
    okeys, oquantities = _owned_pool_arrays(owned_pool)

    rows = db.execute(
        text(f"""
            WITH owned(okey, oqty) AS (
                SELECT * FROM unnest(CAST(:okeys AS text[]), CAST(:oquantities AS integer[]))
            ),
            required AS (
                SELECT
                    cli.list_id,
                    {_KEY_EXPR_SQL} AS key,
                    SUM(cli.quantity) AS req_qty
                FROM card_list_items cli
                JOIN card_lists cl ON cl.id = cli.list_id
                WHERE cl.user_id = :user_id AND cli.section = ANY(CAST(:sections AS text[]))
                GROUP BY cli.list_id, key
            )
            SELECT
                r.list_id AS list_id,
                SUM(r.req_qty)::bigint AS total_required_quantity,
                SUM(LEAST(r.req_qty, COALESCE(o.oqty, 0)))::bigint AS total_owned_applied,
                COUNT(*) FILTER (WHERE r.req_qty > COALESCE(o.oqty, 0)) AS distinct_missing_count
            FROM required r
            LEFT JOIN owned o ON o.okey = r.key
            GROUP BY r.list_id
        """),
        {
            "okeys": okeys,
            "oquantities": oquantities,
            "user_id": user_id,
            "sections": sorted(REQUIRED_LIST_SECTIONS),
        },
    )
    # Lists with zero required cards never appear in `required` (nothing to
    # GROUP BY), so they're absent from the query result entirely - default
    # them to "nothing required, trivially fully buildable", matching what
    # compare_pool([]) would return (total_required_quantity=0 -> coverage
    # 100.0, missing=[] -> is_fully_buildable=True).
    by_list_id = {row.list_id: row for row in rows}

    list_buildability: list[ListBuildability] = []
    for card_list in lists:
        row = by_list_id.get(card_list.id)
        if row is None:
            coverage_percent, is_fully_buildable, total_required_quantity = 100.0, True, 0
        else:
            total_required_quantity = row.total_required_quantity
            coverage_percent = (
                round(row.total_owned_applied / total_required_quantity * 100, 2) if total_required_quantity else 100.0
            )
            is_fully_buildable = row.distinct_missing_count == 0
        list_buildability.append(
            ListBuildability(
                list_id=card_list.id,
                name=card_list.name,
                list_type=card_list.list_type,
                coverage_percent=coverage_percent,
                is_fully_buildable=is_fully_buildable,
                total_required_quantity=total_required_quantity,
            )
        )
    return list_buildability


def compute_leverage_at_scale(db: Session, owned_pool: dict[str, int], *, user_id: int = DEFAULT_USER_ID) -> list[LeverageCandidate]:
    """Same ranking `app.comparison.leverage.compute_leverage` produces,
    restructured to scale to a real ~85,000-list, ~37-million-row
    collection (2026-08-19/20) - see `compute_list_buildability`'s own
    docstring for why holding per-row or even per-list-per-candidate detail
    in Python doesn't work at this scale, OOM or not. `compute_leverage`
    itself is left untouched as the correct, pure, general implementation
    (still used by anything working with a smaller or already-in-memory
    `lists_required` mapping); this is a dashboard-specific fast path for
    the one real caller that now needs to handle the full collection.

    One SQL query computes everything needed per *candidate key* - the
    aggregate demand (for `quantity_needed`), how many lists have this as
    their *only* missing card (`lists_newly_buildable`), and the summed
    per-list coverage-gain contribution (`total_coverage_gain`) - entirely
    server-side. The result is bounded by distinct candidate count (~50,000
    real, confirmed live), not by list count or row count.
    """
    okeys, oquantities = _owned_pool_arrays(owned_pool)

    rows = db.execute(
        text(f"""
            WITH owned(okey, oqty) AS (
                SELECT * FROM unnest(CAST(:okeys AS text[]), CAST(:oquantities AS integer[]))
            ),
            required AS (
                SELECT
                    cli.list_id,
                    {_KEY_EXPR_SQL} AS key,
                    MAX(cli.card_name) AS name,
                    MAX(cli.resolved_oracle_id) AS oracle_id,
                    MAX(cli.resolved_scryfall_card_id) AS scryfall_card_id,
                    SUM(cli.quantity) AS req_qty
                FROM card_list_items cli
                JOIN card_lists cl ON cl.id = cli.list_id
                WHERE cl.user_id = :user_id AND cli.section = ANY(CAST(:sections AS text[]))
                GROUP BY cli.list_id, key
            ),
            list_totals AS (
                SELECT list_id, SUM(req_qty) AS total_required_quantity
                FROM required GROUP BY list_id
            ),
            shortfalls AS (
                SELECT
                    r.list_id,
                    r.key,
                    GREATEST(r.req_qty - COALESCE(o.oqty, 0), 0) AS shortfall,
                    lt.total_required_quantity
                FROM required r
                LEFT JOIN owned o ON o.okey = r.key
                JOIN list_totals lt ON lt.list_id = r.list_id
                WHERE r.req_qty > COALESCE(o.oqty, 0)
            ),
            list_missing_counts AS (
                SELECT list_id, COUNT(*) AS distinct_missing_count
                FROM shortfalls GROUP BY list_id
            ),
            key_totals AS (
                SELECT
                    key,
                    MAX(name) AS name,
                    MAX(oracle_id) AS oracle_id,
                    MAX(scryfall_card_id) AS scryfall_card_id,
                    SUM(req_qty)::bigint AS total_quantity
                FROM required GROUP BY key
            )
            SELECT
                kt.key,
                kt.name,
                kt.oracle_id,
                kt.scryfall_card_id,
                kt.total_quantity,
                COALESCE(agg.lists_newly_buildable, 0) AS lists_newly_buildable,
                COALESCE(agg.total_coverage_gain, 0) AS total_coverage_gain
            FROM key_totals kt
            LEFT JOIN (
                SELECT
                    s.key,
                    COUNT(*) FILTER (WHERE lmc.distinct_missing_count = 1) AS lists_newly_buildable,
                    SUM(
                        CASE WHEN s.total_required_quantity > 0
                        THEN s.shortfall::float / s.total_required_quantity * 100 ELSE 0 END
                    ) AS total_coverage_gain
                FROM shortfalls s
                JOIN list_missing_counts lmc ON lmc.list_id = s.list_id
                GROUP BY s.key
            ) agg ON agg.key = kt.key
        """),
        {
            "okeys": okeys,
            "oquantities": oquantities,
            "user_id": user_id,
            "sections": sorted(REQUIRED_LIST_SECTIONS),
        },
    )

    candidates: list[LeverageCandidate] = []
    for row in rows:
        aggregate_shortfall = max(row.total_quantity - owned_pool.get(row.key, 0), 0)
        if aggregate_shortfall <= 0:
            continue
        candidates.append(
            LeverageCandidate(
                name=row.name,
                oracle_id=row.oracle_id,
                scryfall_card_id=row.scryfall_card_id,
                quantity_needed=aggregate_shortfall,
                lists_newly_buildable=row.lists_newly_buildable,
                total_coverage_gain=round(row.total_coverage_gain, 2),
            )
        )

    candidates.sort(key=lambda c: (c.lists_newly_buildable, c.total_coverage_gain), reverse=True)
    return candidates


def compute_list_missing_cost(
    db: Session, list_buildability: list[ListBuildability], owned_pool: dict[str, int], *, user_id: int = DEFAULT_USER_ID
) -> list[ListMissingCost]:
    """Total cost to complete each list (sum of missing-card prices), using
    the user's default price profile - real market prices only (Scryfall/
    MTGJSON sync, see PRICING.md), never estimated. A list is only included
    if *every* one of its missing cards actually resolved a price - "no fake
    success": a partial total that silently excludes unpriced cards would
    understate the real cost, so it's omitted entirely rather than shown as
    a misleadingly low number.

    `list_buildability` is only used here for its `name`/`list_type` per
    list_id (a tiny lookup) - see `compute_list_buildability`'s own
    docstring for why the missing-card detail itself is computed via SQL
    below instead of Python-side, same reasoning as
    `compute_leverage_at_scale`.
    """
    profile = pricing_service.get_or_create_default_price_profile(db, user_id=user_id)

    # Distinct candidate keys collection-wide, with their oracle_id/
    # scryfall_card_id, needed to look up real prices - reuses the exact
    # same aggregation shape `compute_leverage_at_scale` already needs, but
    # only pulls the small (key, oracle_id, scryfall_card_id) columns since
    # pricing doesn't need per-list detail either.
    key_rows = db.execute(
        text(f"""
            SELECT
                {_KEY_EXPR_SQL} AS key,
                MAX(cli.resolved_oracle_id) AS oracle_id,
                MAX(cli.resolved_scryfall_card_id) AS scryfall_card_id
            FROM card_list_items cli
            JOIN card_lists cl ON cl.id = cli.list_id
            WHERE cl.user_id = :user_id AND cli.section = ANY(CAST(:sections AS text[]))
            GROUP BY key
        """),
        {"user_id": user_id, "sections": sorted(REQUIRED_LIST_SECTIONS)},
    ).all()

    oracle_ids = {r.oracle_id for r in key_rows if r.oracle_id}
    direct_card_ids = {r.scryfall_card_id for r in key_rows if not r.oracle_id and r.scryfall_card_id}
    price_by_oracle, price_by_direct = pricing_service.batch_cheapest_prices(db, oracle_ids, direct_card_ids, profile)

    price_by_key: dict[str, Decimal] = {}
    for r in key_rows:
        price = price_by_oracle.get(r.oracle_id) if r.oracle_id else None
        if price is None and r.scryfall_card_id:
            price = price_by_direct.get(r.scryfall_card_id)
        if price is not None:
            price_by_key[r.key] = price

    if not price_by_key:
        return []
    pkeys, pvalues = zip(*price_by_key.items(), strict=True)
    okeys, oquantities = _owned_pool_arrays(owned_pool)

    rows = db.execute(
        text(f"""
            WITH owned(okey, oqty) AS (
                SELECT * FROM unnest(CAST(:okeys AS text[]), CAST(:oquantities AS integer[]))
            ),
            prices(pkey, price) AS (
                SELECT unnest(CAST(:pkeys AS text[])), unnest(CAST(:pvalues AS text[]))::numeric
            ),
            required AS (
                SELECT
                    cli.list_id,
                    {_KEY_EXPR_SQL} AS key,
                    SUM(cli.quantity) AS req_qty
                FROM card_list_items cli
                JOIN card_lists cl ON cl.id = cli.list_id
                WHERE cl.user_id = :user_id AND cli.section = ANY(CAST(:sections AS text[]))
                GROUP BY cli.list_id, key
            ),
            shortfalls AS (
                SELECT
                    r.list_id,
                    r.key,
                    GREATEST(r.req_qty - COALESCE(o.oqty, 0), 0) AS shortfall
                FROM required r
                LEFT JOIN owned o ON o.okey = r.key
                WHERE r.req_qty > COALESCE(o.oqty, 0)
            )
            SELECT
                s.list_id,
                SUM(s.shortfall * COALESCE(p.price, 0)) AS total_cost
            FROM shortfalls s
            LEFT JOIN prices p ON p.pkey = s.key
            GROUP BY s.list_id
            HAVING COUNT(*) FILTER (WHERE p.price IS NULL) = 0
        """),
        {
            "okeys": okeys,
            "oquantities": oquantities,
            "pkeys": list(pkeys),
            "pvalues": [str(v) for v in pvalues],
            "user_id": user_id,
            "sections": sorted(REQUIRED_LIST_SECTIONS),
        },
    )

    lb_by_id = {lb.list_id: lb for lb in list_buildability}
    results: list[ListMissingCost] = []
    for row in rows:
        lb = lb_by_id.get(row.list_id)
        if lb is None:
            continue  # a list deleted between the two queries - real but rare race, just skip it
        results.append(
            ListMissingCost(list_id=lb.list_id, name=lb.name, list_type=lb.list_type, total_cost=row.total_cost, currency=profile.currency)
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
    owned_pool = build_owned_pool(owned, "oracle")
    list_buildability = compute_list_buildability(db, user_id=user_id)

    lists_fully_buildable = sum(1 for lb in list_buildability if lb.is_fully_buildable)
    average_coverage = (
        round(sum(lb.coverage_percent for lb in list_buildability) / len(list_buildability), 2)
        if list_buildability
        else 0.0
    )
    leverage_candidates = [
        c
        for c in compute_leverage_at_scale(db, owned_pool, user_id=user_id)
        if c.name.strip().lower() not in _BASIC_LAND_NAMES
    ]
    top_leverage = price_leverage_candidates(db, leverage_candidates[:TOP_LEVERAGE_COUNT], user_id=user_id)
    list_missing_cost = compute_list_missing_cost(db, list_buildability, owned_pool, user_id=user_id)

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
        list_missing_cost=list_missing_cost,
    )
