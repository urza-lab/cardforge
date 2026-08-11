from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.lists import CardList, CardListItem, ListType
from app.models.user import DEFAULT_USER_ID

VALID_LIST_TYPES = {t.value for t in ListType}


class InvalidListTypeError(ValueError):
    pass


def list_lists(db: Session, user_id: int = DEFAULT_USER_ID) -> list[CardList]:
    stmt = select(CardList).where(CardList.user_id == user_id).order_by(CardList.created_at)
    return list(db.scalars(stmt))


def create_list(db: Session, *, name: str, list_type: str, user_id: int = DEFAULT_USER_ID) -> CardList:
    if list_type not in VALID_LIST_TYPES:
        raise InvalidListTypeError(f"list_type must be one of {sorted(VALID_LIST_TYPES)}, got '{list_type}'")
    card_list = CardList(user_id=user_id, name=name, list_type=list_type)
    db.add(card_list)
    db.commit()
    db.refresh(card_list)
    return card_list


def get_list(db: Session, list_id: int, user_id: int = DEFAULT_USER_ID) -> CardList | None:
    stmt = select(CardList).where(CardList.id == list_id, CardList.user_id == user_id)
    return db.scalars(stmt).first()


def list_items(db: Session, list_id: int) -> list[CardListItem]:
    stmt = (
        select(CardListItem)
        .where(CardListItem.list_id == list_id)
        .order_by(CardListItem.section, CardListItem.card_name)
    )
    return list(db.scalars(stmt))


def rename_list(db: Session, card_list: CardList, *, name: str) -> CardList:
    card_list.name = name
    db.commit()
    db.refresh(card_list)
    return card_list


def delete_list(db: Session, card_list: CardList) -> None:
    db.delete(card_list)
    db.commit()
