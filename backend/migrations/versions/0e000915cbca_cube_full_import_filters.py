"""cube full import filters

Revision ID: 0e000915cbca
Revises: 9ce6318a6b09
Create Date: 2026-08-21 04:55:35.282255
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '0e000915cbca'
down_revision: str | None = '9ce6318a6b09'
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "cube_full_import_state",
        sa.Column("filter_min_card_count", sa.Integer(), nullable=False, server_default="180"),
    )
    op.add_column("cube_full_import_state", sa.Column("filter_max_card_count", sa.Integer(), nullable=True))
    op.add_column(
        "cube_full_import_state",
        sa.Column("filter_require_description", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "cube_full_import_state",
        sa.Column("filter_top_n", sa.Integer(), nullable=False, server_default="10000"),
    )
    op.add_column("cube_full_import_state", sa.Column("filter_max_total", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("cube_full_import_state", "filter_max_total")
    op.drop_column("cube_full_import_state", "filter_top_n")
    op.drop_column("cube_full_import_state", "filter_require_description")
    op.drop_column("cube_full_import_state", "filter_max_card_count")
    op.drop_column("cube_full_import_state", "filter_min_card_count")
