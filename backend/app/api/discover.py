from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import get_db
from app.schemas.discover import DeckDiscoverySyncStatusRead, PopularDeckPriceRequest, PopularDeckRead
from app.security.ssrf_guard import AuthRequiredError, SsrfBlockedError
from app.services import collection_service, discover_service, pricing_service
from app.source_adapters.errors import SourceFetchError

router = APIRouter(prefix="/api/discover", tags=["discover"])


@router.get("/decks", response_model=list[PopularDeckRead])
def list_popular_decks(
    sort: str = "views",
    color_identity: str | None = None,
    source: str | None = None,
    bracket: int | None = None,
    q: str | None = None,
    has_primer: bool | None = None,
    min_deck_size: int | None = None,
    exclude_theorycrafted: bool = False,
    updated_after_days: int | None = None,
    tag: str | None = None,
    db: Session = Depends(get_db),
) -> list[PopularDeckRead]:
    decks = discover_service.list_popular_decks(
        db,
        sort=sort,
        color_identity=color_identity,
        source=source,
        bracket=bracket,
        q=q,
        has_primer=has_primer,
        min_deck_size=min_deck_size,
        exclude_theorycrafted=exclude_theorycrafted,
        updated_after_days=updated_after_days,
        tag=tag,
    )
    return [PopularDeckRead.model_validate(d) for d in decks]


@router.get("/decks/archidekt-commander-search", response_model=list[PopularDeckRead])
def search_archidekt_commander(commander: str, db: Session = Depends(get_db)) -> list[PopularDeckRead]:
    """Live, on-demand proxy to Archidekt's real `commanderName` search
    filter - see app.services.discover_service.search_archidekt_by_commander
    and app.source_adapters.archidekt.search_by_commander for why this can't
    be a local cache lookup the way Moxfield's commander search is. Only
    ever called on an explicit submit action from the frontend (Enter/
    button, not per keystroke) - deliberately not folded into the regular
    /decks endpoint's `q` filter, since that stays a fast, always-local
    query with no live third-party dependency.
    """
    if not commander.strip():
        return []
    try:
        decks = discover_service.search_archidekt_by_commander(db, commander.strip())
    except SourceFetchError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return [PopularDeckRead.model_validate(d) for d in decks]


@router.get("/decks/status", response_model=DeckDiscoverySyncStatusRead)
def get_sync_status(db: Session = Depends(get_db)) -> DeckDiscoverySyncStatusRead:
    return DeckDiscoverySyncStatusRead.model_validate(discover_service.get_sync_state(db))


@router.post("/decks/sync", response_model=DeckDiscoverySyncStatusRead, status_code=202)
def trigger_sync(db: Session = Depends(get_db)) -> DeckDiscoverySyncStatusRead:
    try:
        state = discover_service.trigger_sync(db)
    except discover_service.SyncAlreadyInProgressError as exc:
        raise HTTPException(status_code=409, detail="a popular-decks sync is already in progress") from exc
    return DeckDiscoverySyncStatusRead.model_validate(state)


@router.post("/decks/{deck_id}/price", response_model=PopularDeckRead)
def price_popular_deck(
    deck_id: int, payload: PopularDeckPriceRequest, db: Session = Depends(get_db)
) -> PopularDeckRead:
    """Lazy pricing (user-requested) - see discover_service.price_popular_deck
    for why this is a real per-deck fetch triggered on demand rather than
    something every cached deck gets eagerly.
    """
    collection_id = payload.collection_id
    if collection_id is None:
        collection_id = collection_service.get_or_create_default_collection(db).id
    elif collection_service.get_collection(db, collection_id) is None:
        raise HTTPException(status_code=404, detail="collection not found")

    user_agent = get_settings().scryfall_user_agent
    try:
        deck = discover_service.price_popular_deck(
            db,
            deck_id,
            collection_id=collection_id,
            price_profile_id=payload.price_profile_id,
            user_agent=user_agent,
        )
    except discover_service.DeckNotFoundError as exc:
        raise HTTPException(status_code=404, detail="popular deck not found") from exc
    except pricing_service.PriceProfileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="price profile not found") from exc
    except SsrfBlockedError as exc:
        raise HTTPException(status_code=400, detail=f"URL rejected: {exc}") from exc
    except AuthRequiredError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except SourceFetchError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return PopularDeckRead.model_validate(deck)
