"""EDHREC synthesized-deck sync orchestration (mirrors
app/services/discover_service.py's FETCHING/CURRENT/FAILED shape) plus the
read-side query the browse API uses. See app/source_adapters/edhrec.py for
the actual scrape+synthesis work and app/models/edhrec.py for why this is
its own cache table, not folded into `PopularDeck`.
"""
from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import delete, insert, select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.queue import get_queue
from app.models.edhrec import EDHREC_SYNC_STATE_ID, EdhrecSyncState, EdhrecSyncStatus, SynthesizedDeck
from app.source_adapters import edhrec

# How many of EDHREC's real top commanders (by its own "Past 2 Years"
# ranking) to synthesize a deck for - each one is a full page fetch (see
# edhrec.py), so this directly sets the sync's real cost. 100 = every
# commander that ranking exposes.
COMMANDER_LIMIT = 100


class SyncAlreadyInProgressError(Exception):
    pass


def get_sync_state(db: Session) -> EdhrecSyncState:
    state = db.get(EdhrecSyncState, EDHREC_SYNC_STATE_ID)
    if state is None:
        raise RuntimeError("edhrec_sync_state row is missing - has the migration been applied?")
    return state


def trigger_sync(db: Session) -> EdhrecSyncState:
    state = get_sync_state(db)
    if state.status == EdhrecSyncStatus.fetching.value:
        raise SyncAlreadyInProgressError

    # Imported here, not at module load - same lazy-import reasoning as
    # discover_service.trigger_sync (avoids a hard API->worker import cycle).
    from app.workers.jobs import sync_edhrec_decks

    get_queue("default").enqueue(sync_edhrec_decks, job_timeout=600)
    state.status = EdhrecSyncStatus.fetching.value
    state.started_at = datetime.now(UTC)
    state.error_message = None
    db.commit()
    db.refresh(state)
    return state


def run_edhrec_sync(db: Session, settings: Settings | None = None, *, limit: int = COMMANDER_LIMIT) -> EdhrecSyncState:
    settings = settings or get_settings()
    state = get_sync_state(db)

    state.status = EdhrecSyncStatus.fetching.value
    state.started_at = datetime.now(UTC)
    state.error_message = None
    db.commit()

    try:
        commanders = edhrec.fetch_popular_commanders(settings.scryfall_user_agent, limit=limit)
        entries, errors = edhrec.fetch_and_synthesize_all(commanders, settings.scryfall_user_agent)

        if not entries:
            raise RuntimeError("; ".join(errors) or "no commanders could be synthesized")

        db.execute(delete(SynthesizedDeck))
        db.execute(
            insert(SynthesizedDeck),
            [
                {
                    "commander_slug": e.commander_slug,
                    "commander_name": e.commander_name,
                    "rank": e.rank,
                    "num_decks": e.num_decks,
                    "color_identity": e.color_identity,
                    "card_count": e.card_count,
                    "deck_text": e.deck_text,
                    "source_url": e.source_url,
                }
                for e in entries
            ],
        )

        state.status = EdhrecSyncStatus.current.value
        state.deck_count = len(entries)
        state.error_message = (
            f"{len(errors)} commander page(s) could not be synthesized: {'; '.join(errors)}"[:1024] if errors else None
        )
        state.finished_at = datetime.now(UTC)
        db.commit()
    except Exception as exc:  # noqa: BLE001 - any failure must be recorded, not silently swallowed
        db.rollback()
        state = get_sync_state(db)
        state.status = EdhrecSyncStatus.failed.value
        state.error_message = str(exc)[:1024]
        state.finished_at = datetime.now(UTC)
        db.commit()
        raise

    return state


def list_synthesized_decks(
    db: Session, *, sort: str = "num_decks", color_identity: str | None = None
) -> list[SynthesizedDeck]:
    order_column = SynthesizedDeck.rank if sort == "rank" else SynthesizedDeck.num_decks
    stmt = select(SynthesizedDeck).order_by(order_column.asc() if sort == "rank" else order_column.desc())
    decks = list(db.scalars(stmt))

    if color_identity:
        allowed = set(color_identity.upper())
        decks = [d for d in decks if set(d.color_identity or []) <= allowed]

    return decks
