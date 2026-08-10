"""Resolves the display name shown for a card: by default, whatever
language the item's own import data recorded (e.g. ManaBox's "Language"
column); optionally forced to one language for every card via
`UserSettings.card_name_language` ("Force card name language" in Settings).

Falls back to the card's canonical English name (`card_name`) whenever no
localized `printed_name` is mirrored for the target language — either
because that printing genuinely was never printed in that language (most
cards, most languages), or because an item only resolved to an oracle_id
(name-only match, see scryfall_resolution) and so has no exact printing to
look a language up against in the first place.
"""
from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.scryfall import ScryfallCard
from app.services.scryfall_resolution import ResolvableItem

DEFAULT_LANGUAGE = "en"


def target_language(item: ResolvableItem, override_language: str | None) -> str:
    if override_language:
        return override_language.lower()
    return (item.language or DEFAULT_LANGUAGE).lower()


def get_display_names(
    db: Session, items: Sequence[ResolvableItem], override_language: str | None = None
) -> dict[int, str]:
    """Returns {item.id: display_name} for every item in `items`."""
    wanted: dict[int, tuple[str, str]] = {}  # item.id -> (oracle_id, lang) worth looking up
    for item in items:
        lang = target_language(item, override_language)
        if item.resolved_oracle_id and lang != DEFAULT_LANGUAGE:
            wanted[item.id] = (item.resolved_oracle_id, lang)

    printed_names: dict[tuple[str, str], str] = {}
    if wanted:
        oracle_ids = {oracle_id for oracle_id, _ in wanted.values()}
        langs = {lang for _, lang in wanted.values()}
        stmt = select(ScryfallCard.oracle_id, ScryfallCard.lang, ScryfallCard.printed_name).where(
            ScryfallCard.oracle_id.in_(oracle_ids),
            ScryfallCard.lang.in_(langs),
            ScryfallCard.printed_name.isnot(None),
        )
        for oracle_id, lang, printed_name in db.execute(stmt):
            printed_names.setdefault((oracle_id, lang), printed_name)

    result: dict[int, str] = {}
    for item in items:
        key = wanted.get(item.id)
        result[item.id] = (printed_names.get(key) if key else None) or item.card_name
    return result
