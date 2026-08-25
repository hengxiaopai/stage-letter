"""Gate 5.4 durable LiveSession consumer metadata.

Revision ID: a54e8b3c2d61
Revises: f52a9d1c4e81
Create Date: 2026-08-26
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a54e8b3c2d61"
down_revision: Union[str, Sequence[str], None] = "f52a9d1c4e81"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "live_sessions",
        sa.Column("provider_room_id", sa.String(length=128), nullable=True),
    )
    op.add_column(
        "live_sessions",
        sa.Column("metadata_source", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "live_sessions",
        sa.Column("metadata_observed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "idx_live_sessions_account_room_started",
        "live_sessions",
        ["platform_account_id", "provider_room_id", "started_at"],
        unique=False,
    )


def downgrade() -> None:
    raise RuntimeError("Gate 5.4 LiveSession consumer parity migration is forward-only")
