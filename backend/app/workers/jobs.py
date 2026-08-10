"""RQ job functions. Enqueued by the API process (see app/api/scryfall.py),
run here in the worker process on its own DB session — a job never reuses
the request-scoped session of whatever request enqueued it.
"""
from __future__ import annotations

import logging

from app.core.database import get_sessionmaker
from app.models.lists import CardList
from app.services import list_refresh_service
from app.source_adapters.scryfall import run_bulk_sync

log = logging.getLogger("cardforge.worker.jobs")


def sync_scryfall_bulk_data() -> None:
    session_local = get_sessionmaker()
    db = session_local()
    try:
        run_bulk_sync(db)
    finally:
        db.close()


def refresh_list_job(list_id: int) -> None:
    session_local = get_sessionmaker()
    db = session_local()
    try:
        card_list = db.get(CardList, list_id)
        if card_list is None:
            log.warning("refresh_list_job: list %d no longer exists, skipping", list_id)
            return
        list_refresh_service.run_refresh(db, card_list)
    finally:
        db.close()


def check_stale_lists() -> None:
    """Periodic sweep - see app.workers.run_worker's staleness-sweep thread,
    which enqueues this job every few hours rather than refreshing lists
    directly (external HTTP calls belong in a job, not the sweep loop).
    """
    session_local = get_sessionmaker()
    db = session_local()
    try:
        count = list_refresh_service.enqueue_stale_refreshes(db)
        log.info("staleness sweep: enqueued %d list refresh(es)", count)
    finally:
        db.close()
