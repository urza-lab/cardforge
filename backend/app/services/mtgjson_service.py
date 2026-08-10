"""MTGJSON price sync orchestration — mirrors app/services/scryfall_service.py
exactly (get_sync_state/trigger_sync/FETCHING race-closing), just against
PriceSyncState's provider-keyed row instead of ScryfallSyncState's fixed
singleton id. See app/source_adapters/mtgjson.py for the actual sync work.
"""
from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.core.queue import get_queue
from app.models.pricing import PriceProvider, PriceSyncState, PriceSyncStatus


class SyncAlreadyInProgressError(Exception):
    pass


def get_sync_state(db: Session) -> PriceSyncState:
    state = db.get(PriceSyncState, PriceProvider.mtgjson.value)
    if state is None:
        raise RuntimeError("price_sync_state row for 'mtgjson' is missing - has the migration been applied?")
    return state


def trigger_sync(db: Session) -> PriceSyncState:
    state = get_sync_state(db)
    if state.status == PriceSyncStatus.fetching.value:
        raise SyncAlreadyInProgressError

    # Imported here, not at module load - avoids a hard import-time
    # dependency from the API process on the worker's job module (see
    # scryfall_service.trigger_sync for the same pattern).
    from app.workers.jobs import sync_mtgjson_prices

    get_queue("pricing").enqueue(sync_mtgjson_prices, job_timeout=900)
    state.status = PriceSyncStatus.fetching.value
    state.started_at = datetime.now(UTC)
    state.error_message = None
    db.commit()
    db.refresh(state)
    return state
