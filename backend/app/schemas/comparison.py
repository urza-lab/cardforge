from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class MissingCardRead(BaseModel):
    name: str
    oracle_id: str | None
    required_quantity: int
    owned_quantity: int
    missing_quantity: int


class ComparisonRowErrorRead(BaseModel):
    row_number: int
    raw: dict[str, Any]
    error: str


class ComparisonResponse(BaseModel):
    mode: str
    total_required_cards: int
    total_required_quantity: int
    total_owned_quantity: int
    coverage_percent: float
    is_fully_buildable: bool
    missing: list[MissingCardRead]
    row_errors: list[ComparisonRowErrorRead]
