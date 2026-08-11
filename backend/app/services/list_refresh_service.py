"""URL-sourced list refresh: re-fetches a CardList's remote deck and syncs
its items against what changed. Mirrors app/source_adapters/scryfall.py's
run_bulk_sync FETCHING/CURRENT/FAILED state machine, but scoped to one
CardList at a time and routed through the existing list_import_service
preview/confirm pipeline (Phase 5's create_preview_from_url + confirm_import)
rather than a bespoke fetch-and-insert loop.

Staleness itself is a read-time computation (is_stale), not a stored status
— a refresh attempt reports FETCHING/CURRENT/FAILED/AUTH_REQUIRED, but
"CURRENT and it's been a while" only becomes interesting when something asks
(the UI, or the periodic sweep below), so there's nothing to keep in sync by
storing it.
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.queue import get_queue
from app.models.lists import CardList, CardListItem, ListRefreshStatus
from app.security.ssrf_guard import AuthRequiredError, SsrfBlockedError
from app.services import list_import_service
from app.source_adapters.errors import SourceFetchError

log = logging.getLogger("cardforge.list_refresh")

# A URL-sourced list counts as stale (surfaced in the UI, picked up by the
# periodic sweep in app.workers.run_worker) once this long has passed since
# its last successful refresh. Not user-configurable yet - a fixed default
# is enough for Phase 5; see ARCHITECTURE.md "Documented default decisions".
STALE_AFTER = timedelta(days=7)


class NotUrlSourcedError(Exception):
    """refresh attempted on a CardList with no source_url (manual import)."""


class RefreshAlreadyInProgressError(Exception):
    pass


def is_stale(card_list: CardList) -> bool:
    if not card_list.source_url:
        return False
    if card_list.refresh_status != ListRefreshStatus.current.value:
        return False
    if card_list.last_refreshed_at is None:
        return False
    # last_refreshed_at comes back tz-naive (all datetime columns here are
    # TIMESTAMP WITHOUT TIME ZONE, always written in UTC) - drop tzinfo from
    # "now" too so the subtraction below doesn't raise.
    now_naive = datetime.now(UTC).replace(tzinfo=None)
    return now_naive - card_list.last_refreshed_at > STALE_AFTER


def trigger_refresh(db: Session, card_list: CardList) -> CardList:
    """Enqueue a refresh job and mark FETCHING immediately - same race-
    closing reasoning as scryfall_service.trigger_sync: two callers racing
    to refresh the same list must not both enqueue a job.
    """
    if not card_list.source_url or not card_list.source_type:
        raise NotUrlSourcedError(card_list.id)
    if card_list.refresh_status == ListRefreshStatus.fetching.value:
        raise RefreshAlreadyInProgressError(card_list.id)

    # Imported here, not at module load - avoids a hard import-time
    # dependency from the API process on the worker's job module (see
    # app.services.scryfall_service.trigger_sync for the same pattern).
    from app.workers.jobs import refresh_list_job

    get_queue("refresh").enqueue(refresh_list_job, card_list.id, job_timeout=120)
    card_list.refresh_status = ListRefreshStatus.fetching.value
    card_list.refresh_error = None
    db.commit()
    db.refresh(card_list)
    return card_list


def run_refresh(db: Session, card_list: CardList) -> CardList:
    """Does the actual fetch+sync. Only ever called from refresh_list_job in
    the worker process, never directly from the API process.

    Everything below the FETCHING commit runs inside one catch-all: an
    exception this function doesn't specifically expect (a DB error, a bug
    elsewhere in the pipeline) must still flip refresh_status to FAILED
    before propagating - otherwise trigger_refresh's "already FETCHING"
    guard would permanently lock the list out of ever being refreshed again
    after a crash. The specific except clauses below handle expected
    failure modes and return normally (no RQ-visible job failure); only a
    genuinely unexpected exception re-raises after being recorded.
    """
    assert card_list.source_url is not None and card_list.source_type is not None

    card_list.refresh_status = ListRefreshStatus.fetching.value
    db.commit()

    try:
        user_agent = get_settings().scryfall_user_agent
        try:
            preview, _deck_name = list_import_service.create_preview_from_url(
                db, card_list=card_list, url=card_list.source_url, user_agent=user_agent
            )
        except AuthRequiredError as exc:
            _mark_failed(db, card_list, ListRefreshStatus.auth_required, str(exc))
            return card_list
        except (SourceFetchError, SsrfBlockedError, list_import_service.UnsupportedUrlError) as exc:
            _mark_failed(db, card_list, ListRefreshStatus.failed, str(exc))
            return card_list

        if preview.duplicate_of_import_id is not None:
            # Remote content hashes identically to our last confirmed import
            # - nothing changed, so there's nothing to replace. Still a
            # real, successful check (see ARCHITECTURE.md "no fake
            # success"), so it stamps last_refreshed_at same as a
            # content-changing refresh would.
            list_import_service.abort_import(db, preview)
            card_list.refresh_status = ListRefreshStatus.current.value
            card_list.refresh_error = None
            card_list.last_refreshed_at = datetime.now(UTC)
            db.commit()
            db.refresh(card_list)
            return card_list

        # Remote content changed: replace this list's items wholesale
        # rather than diffing - a refresh is unattended (no user reviewing
        # a preview), so skip_bad_rows=True - confirm_import sets
        # card_list.refresh_status/last_refreshed_at/refresh_error itself
        # once the new rows are in.
        db.execute(delete(CardListItem).where(CardListItem.list_id == card_list.id))
        list_import_service.confirm_import(db, preview, skip_bad_rows=True)
        db.refresh(card_list)
        return card_list
    except Exception as exc:  # noqa: BLE001 - see docstring: must record FAILED before propagating
        db.rollback()
        card_list = db.get(CardList, card_list.id)  # type: ignore[assignment]
        assert card_list is not None
        _mark_failed(db, card_list, ListRefreshStatus.failed, f"unexpected error: {exc}")
        log.exception("list %d refresh failed unexpectedly", card_list.id)
        raise


def _mark_failed(db: Session, card_list: CardList, status: ListRefreshStatus, message: str) -> None:
    card_list.refresh_status = status.value
    card_list.refresh_error = message[:1024]
    db.commit()
    log.warning("list %d refresh failed (%s): %s", card_list.id, status.value, message)


def enqueue_stale_refreshes(db: Session) -> int:
    """Called by the periodic staleness sweep (see app.workers.run_worker).
    Enqueues a refresh for every URL-sourced list that has gone stale;
    returns how many were enqueued.
    """
    stmt = select(CardList).where(CardList.source_url.is_not(None))
    candidates = [cl for cl in db.scalars(stmt) if is_stale(cl)]
    for card_list in candidates:
        try:
            trigger_refresh(db, card_list)
        except RefreshAlreadyInProgressError:
            continue
    return len(candidates)
