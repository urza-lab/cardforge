"""RQ job functions. Enqueued by the API process (see app/api/scryfall.py),
run here in the worker process on its own DB session — a job never reuses
the request-scoped session of whatever request enqueued it.
"""
from __future__ import annotations

import logging

from app.core.database import get_sessionmaker
from app.source_adapters.scryfall import run_bulk_sync

log = logging.getLogger("cardforge.worker.jobs")


def sync_scryfall_bulk_data() -> None:
    session_local = get_sessionmaker()
    db = session_local()
    try:
        run_bulk_sync(db)
    finally:
        db.close()
