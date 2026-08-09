from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.collection import Collection, CollectionItem
from app.models.user import DEFAULT_USER_ID

DEFAULT_COLLECTION_NAME = "My Collection"


def list_collections(db: Session, user_id: int = DEFAULT_USER_ID) -> list[Collection]:
    stmt = select(Collection).where(Collection.user_id == user_id).order_by(Collection.created_at)
    return list(db.scalars(stmt))


def create_collection(db: Session, name: str, user_id: int = DEFAULT_USER_ID) -> Collection:
    has_existing = db.scalar(select(Collection.id).where(Collection.user_id == user_id).limit(1))
    collection = Collection(user_id=user_id, name=name, is_default=not has_existing)
    db.add(collection)
    db.commit()
    db.refresh(collection)
    return collection


def get_collection(db: Session, collection_id: int, user_id: int = DEFAULT_USER_ID) -> Collection | None:
    stmt = select(Collection).where(Collection.id == collection_id, Collection.user_id == user_id)
    return db.scalars(stmt).first()


def get_or_create_default_collection(db: Session, user_id: int = DEFAULT_USER_ID) -> Collection:
    stmt = select(Collection).where(Collection.user_id == user_id, Collection.is_default.is_(True))
    existing = db.scalars(stmt).first()
    if existing is not None:
        return existing
    return create_collection(db, name=DEFAULT_COLLECTION_NAME, user_id=user_id)


def list_items(db: Session, collection_id: int) -> list[CollectionItem]:
    stmt = (
        select(CollectionItem)
        .where(CollectionItem.collection_id == collection_id)
        .order_by(CollectionItem.card_name, CollectionItem.set_code)
    )
    return list(db.scalars(stmt))
