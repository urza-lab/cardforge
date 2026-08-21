"""Prometheus exporter (Phase 7) — see ARCHITECTURE.md "Metrics backend":
Grafana reads from Prometheus, not Postgres directly. A fresh
`CollectorRegistry` per scrape, populated straight from the same tables
`app.metrics.dashboard_service` aggregates — this is a pull-based exporter
(values computed on each scrape), not counters incremented during request
handling, so there's nothing to get out of sync between server restarts.
No fake/hardcoded values: every gauge here reflects the same live query the
API/dashboard would show, per ARCHITECTURE.md's "no fake success".

Per-list gauges (`cardforge_list_coverage_percent`/`cardforge_list_missing_
cost`) read from `app.metrics.dashboard_cache` instead of calling
`compute_list_buildability`/`compute_list_missing_cost` directly (2026-08-20,
see CLAUDE.md gotcha history): once the real collection passed ~82,000
lists (the CubeCobra full-catalog import), calling those two functions fresh
on *every single scrape* made `/metrics` take ~24.5 minutes and return
~16.8MB - Prometheus's `scrape_timeout` (45s) can never wait that long, so
a restarted Prometheus would just report every scrape as failed with no
data ever landing, forever. The dashboard cache already computes and keeps
this same data warm on a 60s TTL for the Dashboard page (app.metrics.
dashboard_cache) - reusing it here means a scrape only pays the real
computation cost when the cache is genuinely stale (same as a Dashboard
page load would), not on every single scrape.

The per-list series are also capped to a bounded top-N (`_MAX_LIST_SERIES`,
1,000 per dimension as of 2026-08-21, user-requested) rather than one label
set per list. To be precise about *why*, after an earlier version of this
comment overstated it: this is a Grafana-table-usability choice, not a
"Prometheus would fall over" one - a single-node Prometheus handles far
more than a couple thousand gauge series without issue, so a much higher
(or no) cap would still be safe for Prometheus itself. The real, complete,
uncapped table for every single list (all 82,000+) already exists and is
already served on demand with no cap at all - `GET /api/dashboard`
(app.metrics.dashboard_cache, same cache this reads from) returns every
list's real coverage/cost, and the app's own "Decks & Cubes" page already
renders all of it (its row-limit dropdown includes "all"). This cap is
purely about what's worth turning into permanent Grafana/Prometheus time
series for a human glancing at a dashboard panel, not a technical ceiling -
same "bounded top-N over a browsable pool" reasoning as `TOP_LEVERAGE_COUNT`
and Discover Cubes' `DEFAULT_LIST_LIMIT` (gotcha #42).
"""
from __future__ import annotations

from prometheus_client import CollectorRegistry, Gauge, generate_latest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.metrics import dashboard_cache
from app.models.collection import CollectionItem
from app.models.lists import CardList
from app.models.pricing import PriceObservation, PriceProvider, PriceSyncState
from app.models.scryfall import SYNC_STATE_ID, ScryfallSyncState
from app.models.user import DEFAULT_USER_ID

# Two dimensions a human actually cares about in the Grafana panels: highest
# coverage (the "buildability" table) and cheapest to complete (the
# "cheapest cubes" table + the scatter plot needs both metrics for the same
# list_id to plot a point at all). Exporting the union of the top N of each
# keeps both tables meaningful without ever emitting one series per list.
_MAX_LIST_SERIES = 1000


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
    list_missing_cost = Gauge(
        "cardforge_list_missing_cost",
        "Real market cost (default price profile) to buy every missing card for a deck/cube. Only "
        "reported when every missing card actually resolved a price - never a partial/estimated total.",
        ["list_id", "list_name", "list_type", "currency"],
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

    summary = dashboard_cache.get_dashboard_summary_cached(user_id=DEFAULT_USER_ID)

    top_by_coverage = sorted(summary.list_buildability, key=lambda lb: lb.coverage_percent, reverse=True)
    top_by_cost = sorted(summary.list_missing_cost, key=lambda mc: mc.total_cost)
    export_list_ids = {lb.list_id for lb in top_by_coverage[:_MAX_LIST_SERIES]} | {
        mc.list_id for mc in top_by_cost[:_MAX_LIST_SERIES]
    }

    for lb in summary.list_buildability:
        if lb.list_id in export_list_ids:
            list_coverage_percent.labels(
                list_id=str(lb.list_id), list_name=lb.name, list_type=lb.list_type
            ).set(lb.coverage_percent)

    for mc in summary.list_missing_cost:
        if mc.list_id in export_list_ids:
            list_missing_cost.labels(
                list_id=str(mc.list_id), list_name=mc.name, list_type=mc.list_type, currency=mc.currency
            ).set(float(mc.total_cost))

    return generate_latest(registry)
