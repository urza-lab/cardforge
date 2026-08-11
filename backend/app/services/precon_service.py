"""MTGJSON precon sync orchestration (mirrors app/services/discover_service.py's
FETCHING/CURRENT/FAILED shape) plus the read-side "best coverage" query.

Unlike every other discovery source's read side, this one doesn't just
return cached rows — it computes each precon's real buildability coverage
against the caller's collection on every read, via the pure
`app.comparison.engine.compare()` (see app/models/mtgjson_precons.py for why
that's cheap enough to do live: no per-deck DB round-trip, MTGJSON already
gave us each precon's complete resolved card list at sync time).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import delete, insert, select
from sqlalchemy.orm import Session

from app.comparison import ComparisonSettings, RequiredCard, compare
from app.core.config import Settings, get_settings
from app.core.queue import get_queue
from app.models.mtgjson_precons import PRECON_SYNC_STATE_ID, PreconDeck, PreconSyncState, PreconSyncStatus
from app.services.comparison_service import _owned_cards
from app.source_adapters import mtgjson_precons


class SyncAlreadyInProgressError(Exception):
    pass


@dataclass(frozen=True)
class PreconCoverage:
    deck: PreconDeck
    coverage_percent: float
    is_fully_buildable: bool
    missing_count: int


def get_sync_state(db: Session) -> PreconSyncState:
    state = db.get(PreconSyncState, PRECON_SYNC_STATE_ID)
    if state is None:
        raise RuntimeError("precon_sync_state row is missing - has the migration been applied?")
    return state


def trigger_sync(db: Session) -> PreconSyncState:
    state = get_sync_state(db)
    if state.status == PreconSyncStatus.fetching.value:
        raise SyncAlreadyInProgressError

    # Imported here, not at module load - same lazy-import reasoning as
    # discover_service.trigger_sync (avoids a hard API->worker import cycle).
    from app.workers.jobs import sync_precon_decks

    # 190 real decks, one HTTP fetch each, paced at
    # mtgjson_precons.PRECON_REQUEST_DELAY_SECONDS (0.3s) = ~60s of pure
    # pacing plus real request time. 1800s matches the same generous
    # headroom discover_service.trigger_sync settled on after gotcha #31,
    # rather than re-guessing a tight number for yet another multi-request
    # sync loop.
    get_queue("default").enqueue(sync_precon_decks, job_timeout=1800)
    state.status = PreconSyncStatus.fetching.value
    state.started_at = datetime.now(UTC)
    state.error_message = None
    db.commit()
    db.refresh(state)
    return state


def run_precon_sync(db: Session, settings: Settings | None = None) -> PreconSyncState:
    settings = settings or get_settings()
    state = get_sync_state(db)

    state.status = PreconSyncStatus.fetching.value
    state.started_at = datetime.now(UTC)
    state.error_message = None
    db.commit()

    try:
        entries, errors = mtgjson_precons.fetch_precon_decks(settings.scryfall_user_agent)

        if not entries:
            raise RuntimeError("; ".join(errors) or "no precon decks could be fetched")

        db.execute(delete(PreconDeck))
        db.execute(
            insert(PreconDeck),
            [
                {
                    "file_name": e.file_name,
                    "name": e.name,
                    "commander_names": e.commander_names,
                    "release_date": e.release_date,
                    "source_url": e.source_url,
                    "card_count": e.card_count,
                    "cards": e.cards,
                    "deck_text": e.deck_text,
                }
                for e in entries
            ],
        )

        state.status = PreconSyncStatus.current.value
        state.deck_count = len(entries)
        state.error_message = (
            f"{len(errors)} deck(s) could not be fetched: {'; '.join(errors)}"[:1024] if errors else None
        )
        state.finished_at = datetime.now(UTC)
        db.commit()
    except Exception as exc:  # noqa: BLE001 - any failure must be recorded, not silently swallowed
        db.rollback()
        state = get_sync_state(db)
        state.status = PreconSyncStatus.failed.value
        state.error_message = str(exc)[:1024]
        state.finished_at = datetime.now(UTC)
        db.commit()
        raise

    return state


def list_precon_decks_with_coverage(db: Session, *, collection_id: int, limit: int | None = None) -> list[PreconCoverage]:
    """Every real precon's real buildability coverage against `collection_id`,
    ranked highest-coverage-first - this is the actual "best coverage"
    answer to the user's own request, not just a browse list. Computed
    fresh on every call (see module docstring) so it's always accurate
    against the collection's *current* state, never a stale cached
    percentage from whenever the collection last changed.
    """
    decks = list(db.scalars(select(PreconDeck)))
    owned = _owned_cards(db, collection_id)

    results: list[PreconCoverage] = []
    for deck in decks:
        required = [
            RequiredCard(name=c["name"], quantity=c["quantity"], oracle_id=c.get("oracle_id")) for c in deck.cards
        ]
        result = compare(owned, required, ComparisonSettings(mode="oracle"))
        results.append(
            PreconCoverage(
                deck=deck,
                coverage_percent=result.coverage_percent,
                is_fully_buildable=result.is_fully_buildable,
                missing_count=len(result.missing),
            )
        )

    results.sort(key=lambda r: r.coverage_percent, reverse=True)
    return results[:limit] if limit else results
