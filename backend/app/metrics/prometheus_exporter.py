"""Prometheus exporter (Phase 7) — see ARCHITECTURE.md "Metrics backend":
Grafana reads from Prometheus, not Postgres directly. A fresh
`CollectorRegistry` per scrape, populated straight from the same tables
`app.metrics.dashboard_service` aggregates — this is a pull-based exporter
(values computed on each scrape), not counters incremented during request
handling, so there's nothing to get out of sync between server restarts.
No fake/hardcoded values: every gauge here reflects the same live query the
API/dashboard would show, per ARCHITECTURE.md's "no fake success".
"""
from __future__ import annotations

from prometheus_client import CollectorRegistry, Gauge, generate_latest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.metrics.dashboard_service import compute_list_buildability
from app.models.collection import CollectionItem
from app.models.lists import CardList
from app.models.pricing import PriceObservation, PriceProvider, PriceSyncState
from app.models.scryfall import SYNC_STATE_ID, ScryfallSyncState


def render_metrics(db: Session) -> bytes:
    registry = CollectorRegistry()

    collection_items = Gauge(
        "cardforge_collection_items_total", "Distinct collection items (default collection)", registry=registry
    )
    collection_quantity = Gauge(
        "cardforge_collection_quantity_total", "Total card quantity in the default collection", registry=registry
    )
    lists_total = Gauge("cardforge_lists_total", "Number of decks/cubes by type", ["list_type"], registry=registry)
    scryfall_cards_total = Gauge(
        "cardforge_scryfall_cards_total", "Printings mirrored from the last Scryfall sync", registry=registry
    )
    scryfall_sync_up = Gauge(
        "cardforge_scryfall_sync_up", "1 if the last Scryfall sync succeeded (status=CURRENT), else 0", registry=registry
    )
    mtgjson_prices_total = Gauge(
        "cardforge_mtgjson_prices_total", "Price observations from the last MTGJSON sync", registry=registry
    )
    mtgjson_sync_up = Gauge(
        "cardforge_mtgjson_sync_up", "1 if the last MTGJSON sync succeeded (status=CURRENT), else 0", registry=registry
    )
    price_observations_total = Gauge(
        "cardforge_price_observations_total", "Price observations by provider", ["provider"], registry=registry
    )
    list_coverage_percent = Gauge(
        "cardforge_list_coverage_percent",
        "Buildability coverage percent (0-100) of each deck/cube against the default collection",
        ["list_id", "list_name", "list_type"],
        registry=registry,
    )

    collection_items.set(db.scalar(select(func.count(CollectionItem.id))) or 0)
    collection_quantity.set(db.scalar(select(func.coalesce(func.sum(CollectionItem.quantity), 0))) or 0)

    for list_type, count in db.execute(select(CardList.list_type, func.count(CardList.id)).group_by(CardList.list_type)):
        lists_total.labels(list_type=list_type).set(count)

    scryfall_state = db.get(ScryfallSyncState, SYNC_STATE_ID)
    scryfall_cards_total.set(scryfall_state.card_count if scryfall_state else 0)
    scryfall_sync_up.set(1 if scryfall_state and scryfall_state.status == "CURRENT" else 0)

    mtgjson_state = db.get(PriceSyncState, PriceProvider.mtgjson.value)
    mtgjson_prices_total.set(mtgjson_state.price_count if mtgjson_state else 0)
    mtgjson_sync_up.set(1 if mtgjson_state and mtgjson_state.status == "CURRENT" else 0)

    for provider, count in db.execute(
        select(PriceObservation.provider, func.count(PriceObservation.id)).group_by(PriceObservation.provider)
    ):
        price_observations_total.labels(provider=provider).set(count)

    list_buildability, _ = compute_list_buildability(db)
    for lb in list_buildability:
        list_coverage_percent.labels(
            list_id=str(lb.list_id), list_name=lb.name, list_type=lb.list_type
        ).set(lb.coverage_percent)

    return generate_latest(registry)
