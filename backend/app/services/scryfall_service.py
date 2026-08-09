from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.queue import get_queue
from app.models.scryfall import SYNC_STATE_ID, ScryfallSyncState, ScryfallSyncStatus


class SyncAlreadyInProgressError(Exception):
    pass


def get_sync_state(db: Session) -> ScryfallSyncState:
    state = db.get(ScryfallSyncState, SYNC_STATE_ID)
    if state is None:
        raise RuntimeError("scryfall_sync_state row is missing - has the migration been applied?")
    return state


def trigger_sync(db: Session) -> ScryfallSyncState:
    """Enqueue a bulk sync job and mark FETCHING immediately.

    Marking FETCHING here (not just inside the job once a worker picks it
    up) closes the race where two requests both see NOT_STARTED/CURRENT and
    both enqueue a job — the second caller sees FETCHING and is rejected.
    The job (app.source_adapters.scryfall.run_bulk_sync) re-asserts the same
    state when it actually starts running, so this is consistent either way.
    """
    state = get_sync_state(db)
    if state.status == ScryfallSyncStatus.fetching.value:
        raise SyncAlreadyInProgressError

    # Imported here, not at module load, to avoid a hard import-time
    # dependency from the API process on the worker's job module for what is
    # really just a function reference RQ serializes by name.
    from app.workers.jobs import sync_scryfall_bulk_data

    get_queue().enqueue(sync_scryfall_bulk_data, job_timeout=900)
    state.status = ScryfallSyncStatus.fetching.value
    state.started_at = datetime.now(UTC)
    state.error_message = None
    db.commit()
    db.refresh(state)
    return state


def maybe_auto_trigger_sync(db: Session, settings: Settings | None = None) -> None:
    """Called once at API startup. Only fires for a database that has never
    been synced (NOT_STARTED) — a prior FAILED sync does not auto-retry on
    every restart (that could hammer Scryfall if something is persistently
    broken, e.g. no outbound network); the user re-triggers it manually from
    the System Status page instead.
    """
    settings = settings or get_settings()
    if not settings.scryfall_bulk_auto_download:
        return
    state = get_sync_state(db)
    if state.status == ScryfallSyncStatus.not_started.value:
        trigger_sync(db)
